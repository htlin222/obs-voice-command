"""edge-tts 多聲音矩陣：不同聲音合成指令語音 → ASR → matcher，驗證觸發。

用法：uv run python tools/voice_matrix.py
需要網路（edge-tts）與 macOS afconvert；合成結果快取在 ~/.cache/obs-voice-command/tts-matrix/。
每個 clip 使用全新 Asr 實例，避免串流狀態殘留造成偽陽性。
"""
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

from obs_voice_command.asr import Asr, ensure_model
from obs_voice_command.config import load_config
from obs_voice_command.matcher import Matcher

CACHE = Path.home() / ".cache" / "obs-voice-command" / "tts-matrix"
CACHE.mkdir(parents=True, exist_ok=True)

VOICES = [
    "zh-CN-XiaoxiaoNeural",           # 女 大陸
    "zh-CN-XiaoyiNeural",             # 女 大陸 活潑
    "zh-CN-YunxiNeural",              # 男 大陸
    "zh-CN-YunjianNeural",            # 男 大陸 激情
    "zh-TW-HsiaoChenNeural",          # 女 台灣
    "zh-TW-HsiaoYuNeural",            # 女 台灣
    "zh-TW-YunJheNeural",             # 男 台灣
    "zh-CN-liaoning-XiaobeiNeural",   # 女 東北腔
]
CASES = [("這邊來個特寫", "zoom_in"), ("退回全畫面", "zoom_out")]
NEGATIVES = [("zh-CN-XiaoxiaoNeural", "今天天氣真不錯"), ("zh-TW-YunJheNeural", "我們來看下一頁")]


def synth(voice: str, text: str, out_wav: Path) -> bool:
    mp3 = out_wav.with_suffix(".mp3")
    if not out_wav.exists():
        r = subprocess.run(
            ["uvx", "edge-tts", "--voice", voice, "--text", text, "--write-media", str(mp3)],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print(f"  synth FAILED: {r.stderr.strip()[:100]}")
            return False
        r = subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(mp3), str(out_wav)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  convert FAILED: {r.stderr.strip()[:100]}")
            return False
    return True


def load_wav(p: Path) -> np.ndarray:
    w = wave.open(str(p))
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def run_pipeline(samples: np.ndarray, asr: Asr, matcher: Matcher):
    actions, final_text = [], ""
    padded = np.concatenate([samples, np.zeros(16000, dtype=np.float32)])
    for i in range(0, len(padded), 1600):
        text, endpoint = asr.feed(padded[i:i + 1600])
        if text:
            final_text = text
        a = matcher.feed(text, now=time.monotonic())
        if a:
            actions.append(a)
        if endpoint:
            matcher.reset_utterance()
    return actions, final_text


def main() -> int:
    cfg = load_config(Path("/nonexistent.toml"))
    model_dir = ensure_model()
    fails = 0

    def check(voice: str, phrase: str, expect: list[str], wav: Path) -> None:
        nonlocal fails
        actions, heard = run_pipeline(load_wav(wav), Asr(model_dir), Matcher(cfg.commands))
        ok = actions == expect
        if not ok:
            fails += 1
        print(f"{'✓' if ok else '✗'} {voice:34s} {phrase} → {actions} (聽到: {heard!r})")

    for voice in VOICES:
        for phrase, expect in CASES:
            wav = CACHE / f"{voice}_{expect}.wav"
            if not synth(voice, phrase, wav):
                fails += 1
                continue
            check(voice, phrase, [expect], wav)

    for voice, phrase in NEGATIVES:
        wav = CACHE / f"neg_{voice}.wav"
        if synth(voice, phrase, wav):
            check(voice, f"[負向] {phrase}", [], wav)

    total = len(VOICES) * len(CASES) + len(NEGATIVES)
    print(f"\n結果: {total - fails}/{total} 通過")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
