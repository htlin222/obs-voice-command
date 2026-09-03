"""Streaming ASR using sherpa-onnx with bilingual Chinese-English model."""

import importlib.util
from pathlib import Path

from .model import CACHE_DIR, MODEL_SUBDIR, MODEL_URL, ModelError, ensure_model  # noqa: F401


def _ensure_onnxruntime_dylib() -> None:
    """sherpa-onnx 1.13.x macOS wheel 漏包 libonnxruntime.dylib（上游打包 bug）；
    缺少時從 onnxruntime 套件 symlink 過去。任何檔案系統錯誤都不致命，
    留給 import sherpa_onnx 自己報錯。"""
    try:
        spec = importlib.util.find_spec("sherpa_onnx")
        if spec is None or not spec.submodule_search_locations:
            return
        lib_dir = Path(spec.submodule_search_locations[0]) / "lib"
        link = lib_dir / "libonnxruntime.dylib"
        if link.is_symlink() and not link.exists():
            link.unlink()  # 壞掉的 symlink（例如 onnxruntime 升級後）重建
        if link.exists():
            return
        ort_spec = importlib.util.find_spec("onnxruntime")
        if ort_spec is None or not ort_spec.submodule_search_locations:
            return
        capi = Path(ort_spec.submodule_search_locations[0]) / "capi"
        for dylib in sorted(capi.glob("libonnxruntime.*.dylib")):
            link.symlink_to(dylib)
            return
    except (OSError, ValueError):
        return


_ensure_onnxruntime_dylib()

import numpy as np  # noqa: E402
import sherpa_onnx  # noqa: E402
from opencc import OpenCC  # noqa: E402


class Asr:
    """Streaming ASR using sherpa-onnx transducer model."""

    def __init__(self, model_dir: Path) -> None:
        """Initialize ASR with model directory.

        Args:
            model_dir: Path to extracted model directory.
        """
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(model_dir / "joiner-epoch-99-avg-1.int8.onnx"),
            enable_endpoint_detection=True,
            sample_rate=16000,
            feature_dim=80,
        )
        self._stream = self.recognizer.create_stream()
        # 模型詞表輸出簡體；轉成台灣繁體（s2twp 含用語轉換）
        self._cc = OpenCC("s2twp")

    def feed(self, samples: np.ndarray) -> tuple[str, bool]:
        """Feed audio samples and return recognized text + endpoint flag.

        Args:
            samples: numpy array, float32, mono, 16kHz.

        Returns:
            (text, endpoint_detected)
        """
        # Feed audio
        self._stream.accept_waveform(16000, samples)

        # Decode as much as possible
        while self.recognizer.is_ready(self._stream):
            self.recognizer.decode_stream(self._stream)

        # Get current result
        text = self._cc.convert(self.recognizer.get_result(self._stream))

        # Check for endpoint
        endpoint = self.recognizer.is_endpoint(self._stream)
        if endpoint:
            self.recognizer.reset(self._stream)

        return (text, endpoint)
