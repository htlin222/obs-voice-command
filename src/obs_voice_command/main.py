"""主程式：音訊 → ASR → 比對 → zoom 控制。"""
import argparse
import queue
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice

from .asr import Asr, ensure_model
from .config import load_config
from .matcher import Matcher
from .mouse import get_displays, get_mouse_pos, locate
from .obs_client import ObsClient
from .zoom import compute_transform, apply_deadzone, smooth, Transform
from . import os_zoom


class ZoomController(threading.Thread):
    """Runs at 30fps, manages zoom state and applies transforms."""

    def __init__(
        self,
        obs,
        item,
        orig,
        canvas,
        src,
        zoom_cfg,
        displays,
        dry_run,
    ):
        super().__init__(daemon=True)
        self._obs = obs
        self._item = item
        self._orig = orig
        self._canvas = canvas
        self._src = src
        self._zoom_cfg = zoom_cfg
        self._displays = displays
        self._dry_run = dry_run

        # State
        self._target_z = 1.0
        self._cur_z = 1.0
        self._cur_cx = src[0] / 2.0
        self._cur_cy = src[1] / 2.0
        self._target_cx = self._cur_cx
        self._target_cy = self._cur_cy

        # Thread control
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._idle = True

    def handle(self, action: str) -> None:
        """Handle zoom_in / zoom_out actions from main thread."""
        with self._lock:
            if action == "zoom_in":
                if self._target_z == 1.0:
                    # Initialize: get current mouse position in source pixels
                    m = self._mouse_src_px()
                    if m:
                        self._target_cx, self._target_cy = m
                        self._cur_cx, self._cur_cy = m
                    self._target_z = self._zoom_cfg.level
                    print("[ZOOM] in")
                else:
                    print("[ZOOM] already in that state, ignored")

            elif action == "zoom_out":
                if self._target_z > 1.0:
                    self._target_z = 1.0
                    print("[ZOOM] out")
                else:
                    print("[ZOOM] already in that state, ignored")

    def _mouse_src_px(self) -> tuple[float, float] | None:
        """Get current mouse position in source pixels, or None if not on any display."""
        try:
            mouse_pos = get_mouse_pos()
            result = locate(mouse_pos, self._displays)
            if result:
                _, px, py = result
                return (px, py)
        except Exception:
            pass
        return None

    def run(self) -> None:
        """Main loop: tick at 30fps, apply transforms."""
        frame_time = 1.0 / 30.0

        while not self._stop_event.is_set():
            try:
                start = time.time()

                # Decide what to send while holding lock
                with self._lock:
                    # 1. Update target center if zoomed in
                    if self._target_z > 1.0:
                        m = self._mouse_src_px()
                        if m:
                            radius = (self._src[0] / self._target_z) * self._zoom_cfg.deadzone
                            self._target_cx, self._target_cy = apply_deadzone(
                                self._target_cx, self._target_cy, m[0], m[1], radius
                            )

                    # 2. Smooth zoom and center
                    self._cur_z = smooth(
                        self._cur_z, self._target_z, self._zoom_cfg.smoothing
                    )
                    self._cur_cx = smooth(
                        self._cur_cx, self._target_cx, self._zoom_cfg.smoothing
                    )
                    self._cur_cy = smooth(
                        self._cur_cy, self._target_cy, self._zoom_cfg.smoothing
                    )

                    # 3. Compute transform
                    t = compute_transform(
                        self._orig,
                        self._canvas,
                        self._src,
                        self._cur_z,
                        self._cur_cx,
                        self._cur_cy,
                    )

                    # 4. Idle optimization: decide what to send
                    if self._cur_z == 1.0 and self._target_z == 1.0:
                        to_send = None if self._idle else self._orig
                        self._idle = True
                    else:
                        self._idle = False
                        to_send = t

                # Send OUTSIDE the lock to avoid blocking handle()
                if to_send is not None:
                    self._send_transform(to_send)

                # Sleep to maintain 30fps
                elapsed = time.time() - start
                sleep_time = max(0, frame_time - elapsed)
                time.sleep(sleep_time)

            except Exception as e:
                print(f"[ZOOM] controller thread died: {e!r}")
                break

    def _send_transform(self, t: Transform) -> None:
        """Send transform to OBS or print if dry-run."""
        if self._dry_run:
            print(f"[TRANSFORM] x={t.pos_x:.1f} y={t.pos_y:.1f} sx={t.scale_x:.2f} sy={t.scale_y:.2f}")
        else:
            try:
                self._obs.set_transform(self._item, t)
            except Exception as e:
                print(f"[ERROR] Failed to set transform: {e}")
                # Attempt reconnect every 3s
                while not self._stop_event.is_set():
                    time.sleep(3)
                    if self._stop_event.is_set():
                        break
                    try:
                        self._obs.connect()
                        # Restore original transform
                        self._obs.set_transform(self._item, self._orig)
                        # Reset state
                        with self._lock:
                            self._target_z = 1.0
                            self._cur_z = 1.0
                            self._cur_cx = self._src[0] / 2.0
                            self._cur_cy = self._src[1] / 2.0
                            self._target_cx = self._cur_cx
                            self._target_cy = self._cur_cy
                            self._idle = True
                        print("[RECONNECT] Restored to original transform")
                        break
                    except Exception as reconnect_err:
                        print(f"[RECONNECT] Still failing: {reconnect_err}")

    def stop(self) -> None:
        """Stop the controller and restore original transform."""
        self._stop_event.set()
        self.join(timeout=2)

        # Best-effort restore
        if not self._dry_run:
            try:
                self._obs.set_transform(self._item, self._orig)
            except Exception:
                pass


def main(args) -> None:
    """Main program flow."""
    # Load config
    cfg = load_config(Path(args.config))

    # Load ASR model
    print("Loading ASR model...")
    asr = Asr(ensure_model())

    # Get displays for mouse tracking (needed in both normal and dry-run modes)
    displays = get_displays()

    # Setup OBS and canvas info（--os 模式走系統縮放，不需要 OBS）
    if not args.dry_run and not args.os:
        obs = ObsClient(cfg.obs.host, cfg.obs.port, cfg.obs.password)
        try:
            obs.connect()
        except ConnectionError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        try:
            item = obs.find_display_capture(cfg.obs.scene, cfg.obs.source)
        except RuntimeError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        orig = obs.get_transform(item)
        canvas = obs.get_canvas_size()
        src = (item.source_width, item.source_height)
    else:
        obs = None
        item = None
        orig = Transform(0, 0, 1, 1)
        canvas = (1920, 1080)
        # Use first display's pixel size
        if displays:
            first = displays[0]
            src = (first.width_px, first.height_px)
        else:
            src = (1920, 1080)

    # Build matcher
    matcher = Matcher(cfg.commands)

    # Start zoom controller
    controller = None
    if not args.os:
        controller = ZoomController(
            obs, item, orig, canvas, src, cfg.zoom, displays, args.dry_run
        )
        controller.start()

    # Setup audio input
    audio_queue: queue.Queue[np.ndarray] = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[AUDIO] {status}")
        audio_queue.put(indata[:, 0].copy())

    try:
        stream = sounddevice.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            blocksize=1600,
            device=cfg.audio.device or None,
            callback=audio_callback,
        )
    except sounddevice.PortAudioError as e:
        print(f"[ERROR] 麥克風開啟失敗 — 檢查「系統設定 → 隱私權與安全性 → 麥克風」權限。錯誤: {e}")
        sys.exit(1)

    # Setup SIGTERM handler
    def sigterm_handler(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, sigterm_handler)

    # Main loop
    try:
        with stream:
            last_text = ""
            while True:
                try:
                    chunk = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                text, endpoint = asr.feed(chunk)

                # Print ASR text if changed
                if text != last_text:
                    print(f"\r[ASR] {text}", end="", flush=True)
                    last_text = text

                # Check for trigger
                action = matcher.feed(text, now=time.monotonic())
                if action:
                    print()  # newline before trigger
                    print(f"[TRIGGER] {action}")
                    if args.os:
                        if args.dry_run:
                            print(f"[OS-ZOOM] {action} (dry-run, 不送出按鍵)")
                        elif action == "zoom_in":
                            os_zoom.zoom_in(target=cfg.zoom.os_level)
                            print(f"[OS-ZOOM] in → {cfg.zoom.os_level}x")
                        else:
                            os_zoom.zoom_out()
                            print("[OS-ZOOM] out")
                    else:
                        controller.handle(action)

                # Reset on endpoint
                if endpoint:
                    matcher.reset_utterance()
                    if text:
                        print()  # newline after utterance

    except KeyboardInterrupt:
        pass
    finally:
        if controller is not None:
            controller.stop()
        print("bye")


def cli() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Voice-commanded zoom-to-mouse for OBS")
    parser.add_argument(
        "--config",
        type=str,
        default="config.toml",
        help="Path to config file (default: config.toml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print transforms instead of sending to OBS",
    )
    parser.add_argument(
        "--os",
        action="store_true",
        help="用真 macOS 螢幕縮放（輔助使用 Zoom）取代 OBS transform 縮放；"
             "同一組語音詞，需開啟「使用鍵盤快速鍵來縮放」與終端機輔助使用權限",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List audio devices and exit",
    )

    args = parser.parse_args()

    if args.list_devices:
        print(sounddevice.query_devices())
        return

    main(args)
