"""主程式：音訊 → ASR → 比對 → zoom 控制。"""
import argparse
import queue
import signal
import stat
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice

from .asr import Asr, ensure_model
from .config import ConfigError, load_config
from .matcher import Matcher
from .model import ModelError
from .mouse import get_displays, get_mouse_pos, locate
from .obs_client import ObsClient
from .zoom import compute_transform, apply_deadzone, smooth, Transform
from . import os_zoom

AUDIO_QUEUE_MAX = 100          # 每塊 0.1 秒 → 最多緩衝 10 秒，避免 ASR 落後時記憶體無限成長
CONTROLLER_MAX_FAILURES = 30   # 連續 30 個 tick（約 1 秒）都失敗才放棄


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
        super().__init__(daemon=True, name="zoom-controller")
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

    def _reset_state(self) -> None:
        """回到未縮放的初始狀態（呼叫端須持有 _lock）。"""
        self._target_z = 1.0
        self._cur_z = 1.0
        self._cur_cx = self._src[0] / 2.0
        self._cur_cy = self._src[1] / 2.0
        self._target_cx = self._cur_cx
        self._target_cy = self._cur_cy
        self._idle = True

    def run(self) -> None:
        """Main loop: tick at 30fps, apply transforms.

        單次 tick 失敗（例如滑鼠座標暫時讀不到）只記錄並繼續；
        連續失敗超過 CONTROLLER_MAX_FAILURES 才結束執行緒，由主迴圈偵測後退出。
        """
        frame_time = 1.0 / 30.0
        failures = 0

        while not self._stop_event.is_set():
            try:
                start = time.monotonic()

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

                failures = 0

                # Sleep to maintain 30fps
                elapsed = time.monotonic() - start
                self._stop_event.wait(max(0.0, frame_time - elapsed))

            except Exception as e:
                failures += 1
                print(f"[ZOOM] tick failed ({failures}/{CONTROLLER_MAX_FAILURES}): {e!r}")
                if failures >= CONTROLLER_MAX_FAILURES:
                    print("[ZOOM] controller thread giving up")
                    break
                self._stop_event.wait(frame_time)

    def _send_transform(self, t: Transform) -> None:
        """Send transform to OBS or print if dry-run."""
        if self._dry_run:
            print(f"[TRANSFORM] x={t.pos_x:.1f} y={t.pos_y:.1f} sx={t.scale_x:.2f} sy={t.scale_y:.2f}")
            return

        try:
            self._obs.set_transform(self._item, t)
        except Exception as e:
            print(f"[ERROR] Failed to set transform: {e}")
            # Attempt reconnect every 3s；用 stop_event.wait 讓 stop() 能立刻中斷
            while not self._stop_event.wait(3):
                try:
                    self._obs.connect()
                    # Restore original transform
                    self._obs.set_transform(self._item, self._orig)
                    with self._lock:
                        self._reset_state()
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


def _warn_if_config_exposed(path: Path, has_password: bool) -> None:
    """config.toml 含 OBS 密碼卻對其他使用者可讀時提醒。"""
    if not has_password or sys.platform == "win32":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"[WARN] {path} 內含 OBS 密碼但其他使用者可讀；建議執行: chmod 600 {path}")


def main(args) -> int:
    """Main program flow. 回傳 process exit code。"""
    # Load config
    config_path = Path(args.config)
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"[ERROR] 設定檔錯誤: {e}")
        return 1
    _warn_if_config_exposed(config_path, bool(cfg.obs.password))

    # Load ASR model
    print("Loading ASR model...")
    try:
        asr = Asr(ensure_model())
    except ModelError as e:
        print(f"[ERROR] {e}")
        return 1

    # Get displays for mouse tracking (needed in both normal and dry-run modes)
    displays = get_displays()

    # Setup OBS and canvas info（--os 模式走系統縮放，不需要 OBS）
    obs = None
    if not args.dry_run and not args.os:
        obs = ObsClient(cfg.obs.host, cfg.obs.port, cfg.obs.password)
        try:
            obs.connect()
            item = obs.find_display_capture(cfg.obs.scene, cfg.obs.source)
            orig = obs.get_transform(item)
            canvas = obs.get_canvas_size()
        except (ConnectionError, RuntimeError) as e:
            print(f"[ERROR] {e}")
            obs.disconnect()
            return 1
        src = (item.source_width, item.source_height)
    else:
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

    # Setup audio input（在啟動 controller 之前，開麥失敗時沒有東西要收拾）
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=AUDIO_QUEUE_MAX)
    dropped = 0

    def audio_callback(indata, frames, time_info, status):
        nonlocal dropped
        if status:
            print(f"[AUDIO] {status}")
        chunk = indata[:, 0].copy()
        try:
            audio_queue.put_nowait(chunk)
            return
        except queue.Full:
            pass
        # 處理端落後：丟最舊的一塊，保留最新音訊，避免延遲與記憶體無限累積
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            audio_queue.put_nowait(chunk)
        except queue.Full:
            pass
        dropped += 1
        if dropped == 1 or dropped % 50 == 0:
            print(f"[AUDIO] 辨識跟不上輸入，已丟棄 {dropped} 塊音訊")

    try:
        stream = sounddevice.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            blocksize=1600,
            device=cfg.audio.device or None,
            callback=audio_callback,
        )
    except (sounddevice.PortAudioError, ValueError) as e:
        print(f"[ERROR] 麥克風開啟失敗 — 檢查「系統設定 → 隱私權與安全性 → 麥克風」權限，"
              f"以及 [audio] device 名稱（--list-devices 查詢）。錯誤: {e}")
        if obs is not None:
            obs.disconnect()
        return 1

    # Start zoom controller
    controller = None
    if not args.os:
        controller = ZoomController(
            obs, item, orig, canvas, src, cfg.zoom, displays, args.dry_run
        )
        controller.start()

    # Setup SIGTERM handler
    def sigterm_handler(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, sigterm_handler)

    exit_code = 0
    os_zoomed = False  # --os 模式下是否由本程式放大（離開時只退回自己造成的縮放）
    # Main loop
    try:
        with stream:
            last_text = ""
            while True:
                if controller is not None and not controller.is_alive():
                    print("[ERROR] zoom controller 已停止，結束程式")
                    exit_code = 1
                    break

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
                        os_zoomed = _handle_os_action(
                            action, cfg.zoom.os_level, args.dry_run, os_zoomed
                        )
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
        if obs is not None:
            obs.disconnect()
        if os_zoomed:
            # 離開時把 macOS 縮放退回，不要留使用者在放大的畫面
            try:
                os_zoom.zoom_out()
            except Exception as e:
                print(f"[OS-ZOOM] 退出縮放失敗: {e}")
        print("bye")
    return exit_code


def _handle_os_action(action: str, os_level: float, dry_run: bool, zoomed: bool) -> bool:
    """--os 模式：把動作送到 macOS 縮放；失敗只記錄，不讓主迴圈死掉。
    回傳更新後的「目前由本程式放大中」狀態。"""
    if dry_run:
        print(f"[OS-ZOOM] {action} (dry-run, 不送出按鍵)")
        return zoomed
    try:
        if action == "zoom_in":
            os_zoom.zoom_in(target=os_level)
            print(f"[OS-ZOOM] in → {os_level}x")
            return True
        os_zoom.zoom_out()
        print("[OS-ZOOM] out")
        return False
    except Exception as e:
        print(f"[OS-ZOOM] 失敗: {e}")
        return zoomed


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

    try:
        sys.exit(main(args))
    except KeyboardInterrupt:
        # 例如在下載模型或連線 OBS 途中按 Ctrl-C：安靜結束，不印 traceback
        print("\nbye")
        sys.exit(130)
