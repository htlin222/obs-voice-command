"""Streaming ASR using sherpa-onnx with bilingual Chinese-English model."""

import importlib.util
import tarfile
import urllib.request
from pathlib import Path


def _ensure_onnxruntime_dylib() -> None:
    """sherpa-onnx 1.13.x macOS wheel 漏包 libonnxruntime.dylib（上游打包 bug）；
    缺少時從 onnxruntime 套件 symlink 過去。"""
    spec = importlib.util.find_spec("sherpa_onnx")
    if spec is None or not spec.submodule_search_locations:
        return
    lib_dir = Path(spec.submodule_search_locations[0]) / "lib"
    link = lib_dir / "libonnxruntime.dylib"
    if link.exists():
        return
    ort_spec = importlib.util.find_spec("onnxruntime")
    if ort_spec is None or not ort_spec.submodule_search_locations:
        return
    capi = Path(ort_spec.submodule_search_locations[0]) / "capi"
    for dylib in sorted(capi.glob("libonnxruntime.*.dylib")):
        link.symlink_to(dylib)
        return


_ensure_onnxruntime_dylib()

import numpy as np
import sherpa_onnx  # noqa: E402
from opencc import OpenCC  # noqa: E402

MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2"
)
CACHE_DIR = Path.home() / ".cache" / "obs-voice-command"
MODEL_SUBDIR = "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"


def ensure_model() -> Path:
    """Ensure model is downloaded and extracted. Returns path to model directory."""
    model_dir = CACHE_DIR / MODEL_SUBDIR

    # If model already exists and contains tokens.txt, return it
    if model_dir.exists() and (model_dir / "tokens.txt").exists():
        return model_dir

    # Create cache directory
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Download model
    tar_path = CACHE_DIR / (MODEL_SUBDIR + ".tar.bz2")

    def download_with_progress(url: str, dest: Path) -> None:
        """Download with simple progress output."""
        print(f"Downloading {url} ...")

        def reporthook(block_num: int, block_size: int, total_size: int) -> None:
            downloaded = min(block_num * block_size, total_size)
            total_mb = total_size / (1024 * 1024)
            downloaded_mb = downloaded / (1024 * 1024)
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                print(f"  {downloaded_mb:.1f} MB / {total_mb:.1f} MB ({percent:.1f}%)", end="\r")

        urllib.request.urlretrieve(url, str(dest), reporthook)
        print()  # newline after progress

    download_with_progress(MODEL_URL, tar_path)

    # Extract tarball
    print(f"Extracting to {CACHE_DIR} ...")
    with tarfile.open(str(tar_path), "r:bz2") as tar:
        tar.extractall(str(CACHE_DIR))

    print(f"Model ready at {model_dir}")
    return model_dir


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
