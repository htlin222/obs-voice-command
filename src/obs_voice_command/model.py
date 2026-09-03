"""ASR 模型下載、校驗與安全解壓（不依賴 sherpa-onnx，可單獨測試）。"""
from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2"
)
# 上游 release asset 的 SHA-256；下載後不符即拒用（防止中途被竄改或下載不完整）
MODEL_SHA256 = "27ffbd9ee24ad186d99acc2f6354d7992b27bcab490812510665fa8f9389c5f8"
CACHE_DIR = Path.home() / ".cache" / "obs-voice-command"
MODEL_SUBDIR = "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
MODEL_FILES = (
    "tokens.txt",
    "encoder-epoch-99-avg-1.int8.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.int8.onnx",
)

DOWNLOAD_TIMEOUT = 60.0  # 每次 socket 讀取的逾時秒數（避免網路卡住永遠不回）
MAX_TARBALL_BYTES = 2 * 1024**3  # 遠超 488MB 的上限，防止異常回應塞爆磁碟
_CHUNK = 1024 * 1024


class ModelError(RuntimeError):
    """模型下載 / 校驗 / 解壓失敗。"""


def _model_ready(model_dir: Path) -> bool:
    return all((model_dir / name).is_file() for name in MODEL_FILES)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    """串流下載到 dest.part，完成後 rename；任何失敗都不留半成品在 dest。"""
    if not url.startswith("https://"):
        raise ModelError(f"拒絕非 HTTPS 的模型來源: {url}")
    part = dest.with_name(dest.name + ".part")
    print(f"Downloading {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "obs-voice-command"})
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_TARBALL_BYTES:
                raise ModelError(f"模型檔案過大 ({total} bytes)，中止下載")
            done = 0
            while True:
                block = resp.read(_CHUNK)
                if not block:
                    break
                done += len(block)
                if done > MAX_TARBALL_BYTES:
                    raise ModelError("模型檔案超過大小上限，中止下載")
                out.write(block)
                if total > 0:
                    print(
                        f"  {done / 2**20:.1f} MB / {total / 2**20:.1f} MB "
                        f"({done * 100 / total:.1f}%)",
                        end="\r",
                    )
            print()
            if total and done != total:
                raise ModelError(f"下載不完整：{done}/{total} bytes")
        os.replace(part, dest)
    except (urllib.error.URLError, OSError, ModelError) as e:
        part.unlink(missing_ok=True)
        if isinstance(e, ModelError):
            raise
        raise ModelError(f"下載模型失敗: {e}") from e
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _extract(tar_path: Path, cache_dir: Path, subdir: str) -> Path:
    """安全解壓：只接受 subdir/ 底下的一般檔案與目錄，用 data filter 擋路徑穿越，
    先解到暫存目錄再原子換入，避免留下半套模型。"""
    prefix = subdir + "/"
    tmp_root = Path(tempfile.mkdtemp(prefix=".extract-", dir=cache_dir))
    try:
        with tarfile.open(tar_path, "r:bz2") as tar:
            members = []
            for m in tar:
                if m.name == subdir or m.name.startswith(prefix):
                    if not (m.isfile() or m.isdir()):
                        raise ModelError(f"模型壓縮檔含非預期的項目: {m.name}")
                    members.append(m)
                else:
                    raise ModelError(f"模型壓縮檔含非預期的路徑: {m.name}")
            tar.extractall(tmp_root, members=members, filter="data")
        extracted = tmp_root / subdir
        if not _model_ready(extracted):
            raise ModelError("模型壓縮檔缺少必要檔案")
        final = cache_dir / subdir
        if final.exists():
            shutil.rmtree(final)
        os.replace(extracted, final)
        return final
    except tarfile.TarError as e:
        raise ModelError(f"解壓模型失敗: {e}") from e
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def ensure_model() -> Path:
    """確保模型已下載、校驗並解壓；回傳模型目錄。"""
    model_dir = CACHE_DIR / MODEL_SUBDIR
    if _model_ready(model_dir):
        return model_dir

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tar_path = CACHE_DIR / (MODEL_SUBDIR + ".tar.bz2")

    if tar_path.exists() and _sha256(tar_path) == MODEL_SHA256:
        print("Using previously downloaded archive")
    else:
        tar_path.unlink(missing_ok=True)
        _download(MODEL_URL, tar_path)
        digest = _sha256(tar_path)
        if digest != MODEL_SHA256:
            tar_path.unlink(missing_ok=True)
            raise ModelError(
                "模型校驗失敗（SHA-256 不符），已刪除下載檔。"
                f" expected={MODEL_SHA256} got={digest}"
            )

    print(f"Extracting to {CACHE_DIR} ...")
    _extract(tar_path, CACHE_DIR, MODEL_SUBDIR)
    tar_path.unlink(missing_ok=True)
    print(f"Model ready at {model_dir}")
    return model_dir
