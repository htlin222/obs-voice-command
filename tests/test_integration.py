"""Integration tests: TTS synthesis → ASR → matcher pipeline."""

import shutil
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from obs_voice_command.asr import Asr, ensure_model
from obs_voice_command.config import load_config
from obs_voice_command.matcher import Matcher


# Module-level skip guards
pytestmark = [
    pytest.mark.skipif(
        not (Path.home() / ".cache" / "obs-voice-command" / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" / "tokens.txt").exists(),
        reason="ASR model not cached (488MB download)"
    ),
    pytest.mark.skipif(
        shutil.which("say") is None,
        reason="macOS say not available"
    ),
]


def synth(text: str, path: Path) -> np.ndarray:
    """Synthesize text to 16kHz mono Int16 WAV using macOS say, return float32 samples."""
    subprocess.run(
        ["say", "-v", "Meijia", "--data-format=LEI16@16000", "-o", str(path), text],
        check=True,
    )
    w = wave.open(str(path))
    samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    return samples


def run_pipeline(samples: np.ndarray, asr: Asr, matcher: Matcher) -> list[str]:
    """Feed samples through ASR with 1s trailing silence, return list of triggered actions."""
    triggered = []
    # Add 1s of trailing silence to trigger endpoint
    padded = np.concatenate([samples, np.zeros(16000, dtype=np.float32)])
    now = time.monotonic()
    for i in range(0, len(padded), 1600):
        text, endpoint = asr.feed(padded[i:i+1600])
        action = matcher.feed(text, now=now)
        if action:
            triggered.append(action)
        if endpoint:
            matcher.reset_utterance()
    return triggered


@pytest.fixture(scope="module")
def model_dir():
    """Module-scoped model directory (cached, no download on repeat runs)."""
    return ensure_model()


@pytest.fixture
def asr(model_dir):
    """Function-scoped ASR fixture to ensure clean stream state per test.

    Reuses the cached model directory but creates a fresh Asr instance
    with a new stream to avoid state accumulation across tests.
    """
    return Asr(model_dir)


def test_zoom_in_phrase_triggers(asr, tmp_path):
    """Synthesize '這邊來個特寫' (zoom in phrase), verify ASR → matcher triggers zoom_in."""
    wav_path = tmp_path / "zoom_in.wav"
    samples = synth("這邊來個特寫", wav_path)
    cfg = load_config(Path("nonexistent.toml"))  # use default commands
    matcher = Matcher(cfg.commands)
    actions = run_pipeline(samples, asr, matcher)
    assert actions == ["zoom_in"], f"Expected ['zoom_in'], got {actions}"


def test_zoom_out_phrase_triggers(asr, tmp_path):
    """Synthesize '退回全畫面' (zoom out phrase), verify ASR → matcher triggers zoom_out."""
    wav_path = tmp_path / "zoom_out.wav"
    samples = synth("退回全畫面", wav_path)
    cfg = load_config(Path("nonexistent.toml"))  # use default commands
    matcher = Matcher(cfg.commands)
    actions = run_pipeline(samples, asr, matcher)
    assert actions == ["zoom_out"], f"Expected ['zoom_out'], got {actions}"


def test_unrelated_speech_no_trigger(asr, tmp_path):
    """Synthesize unrelated speech '今天天氣真不錯', verify no action triggered."""
    wav_path = tmp_path / "unrelated.wav"
    samples = synth("今天天氣真不錯", wav_path)
    cfg = load_config(Path("nonexistent.toml"))  # use default commands
    matcher = Matcher(cfg.commands)
    actions = run_pipeline(samples, asr, matcher)
    assert actions == [], f"Expected [], got {actions}"
