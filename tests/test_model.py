"""模型下載 / 校驗 / 解壓的安全性測試（不需要真的模型）。"""
import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from obs_voice_command import model
from obs_voice_command.model import MODEL_FILES, ModelError, _extract, _sha256


def _make_tar(path: Path, entries: dict[str, bytes], extra=None) -> None:
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if extra:
            extra(tar)


def _good_entries(subdir: str) -> dict[str, bytes]:
    return {f"{subdir}/{name}": b"x" for name in MODEL_FILES}


def test_extract_happy_path(tmp_path: Path):
    tar = tmp_path / "m.tar.bz2"
    _make_tar(tar, {**_good_entries("model"), "model/test_wavs/0.wav": b"riff"})
    out = _extract(tar, tmp_path, "model")
    assert out == tmp_path / "model"
    assert all((out / n).is_file() for n in MODEL_FILES)
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".extract-")]


def test_extract_replaces_stale_partial_dir(tmp_path: Path):
    stale = tmp_path / "model"
    stale.mkdir()
    (stale / "garbage").write_text("old")
    tar = tmp_path / "m.tar.bz2"
    _make_tar(tar, _good_entries("model"))
    _extract(tar, tmp_path, "model")
    assert not (stale / "garbage").exists()
    assert (stale / "tokens.txt").is_file()


def test_extract_rejects_path_traversal(tmp_path: Path):
    tar = tmp_path / "m.tar.bz2"
    _make_tar(tar, {**_good_entries("model"), "../evil.txt": b"pwned"})
    with pytest.raises(ModelError):
        _extract(tar, tmp_path, "model")
    assert not (tmp_path.parent / "evil.txt").exists()


def test_extract_rejects_foreign_top_level(tmp_path: Path):
    tar = tmp_path / "m.tar.bz2"
    _make_tar(tar, {**_good_entries("model"), "other/tokens.txt": b"x"})
    with pytest.raises(ModelError):
        _extract(tar, tmp_path, "model")
    assert not (tmp_path / "other").exists()


def test_extract_rejects_symlink_member(tmp_path: Path):
    def add_link(tar):
        info = tarfile.TarInfo("model/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)

    tar = tmp_path / "m.tar.bz2"
    _make_tar(tar, _good_entries("model"), extra=add_link)
    with pytest.raises(ModelError):
        _extract(tar, tmp_path, "model")


def test_extract_rejects_missing_required_files(tmp_path: Path):
    tar = tmp_path / "m.tar.bz2"
    _make_tar(tar, {"model/tokens.txt": b"x"})
    with pytest.raises(ModelError):
        _extract(tar, tmp_path, "model")
    assert not (tmp_path / "model").exists()


def test_sha256_matches_hashlib(tmp_path: Path):
    p = tmp_path / "f"
    p.write_bytes(b"hello" * 1000)
    assert _sha256(p) == hashlib.sha256(b"hello" * 1000).hexdigest()


def test_ensure_model_rejects_bad_checksum(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(model, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(model, "MODEL_SUBDIR", "model")

    def fake_download(url, dest):
        _make_tar(dest, _good_entries("model"))

    monkeypatch.setattr(model, "_download", fake_download)
    with pytest.raises(ModelError, match="SHA-256"):
        model.ensure_model()
    assert not (tmp_path / "model.tar.bz2").exists()  # 壞檔不留


def test_ensure_model_accepts_good_checksum(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(model, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(model, "MODEL_SUBDIR", "model")
    tar = tmp_path / "prebuilt.tar.bz2"
    _make_tar(tar, _good_entries("model"))
    monkeypatch.setattr(model, "MODEL_SHA256", _sha256(tar))

    def fake_download(url, dest):
        dest.write_bytes(tar.read_bytes())

    monkeypatch.setattr(model, "_download", fake_download)
    out = model.ensure_model()
    assert out == tmp_path / "model"
    assert (out / "tokens.txt").is_file()
    assert not (tmp_path / "model.tar.bz2").exists()  # 解壓完清掉壓縮檔
    # 第二次直接命中快取，不再下載
    monkeypatch.setattr(model, "_download", lambda *a: pytest.fail("should not download"))
    assert model.ensure_model() == out


def test_download_rejects_non_https(tmp_path: Path):
    with pytest.raises(ModelError):
        model._download("http://example.com/x.tar.bz2", tmp_path / "x")
    assert not list(tmp_path.iterdir())
