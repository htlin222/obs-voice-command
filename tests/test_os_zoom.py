"""os_zoom 參數驗證與子程序錯誤處理（不真的動 macOS）。"""
import subprocess

import pytest

from obs_voice_command import os_zoom


@pytest.mark.parametrize("bad", [0.0, 1.0, -2.0, float("inf"), float("nan"), 999.0, "2", True])
def test_zoom_in_rejects_bad_target(bad, monkeypatch):
    monkeypatch.setattr(os_zoom, "_defaults", lambda *a: pytest.fail("must validate before running defaults"))
    with pytest.raises(ValueError):
        os_zoom.zoom_in(target=bad)


def test_read_returns_default_when_defaults_fails(monkeypatch):
    monkeypatch.setattr(
        os_zoom, "_defaults",
        lambda *a: subprocess.CompletedProcess(a, 1, "", "does not exist"),
    )
    assert os_zoom.is_zoomed() is False


def test_defaults_missing_binary_raises_oszoomerror(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("defaults")
    monkeypatch.setattr(os_zoom.subprocess, "run", boom)
    with pytest.raises(os_zoom.OsZoomError):
        os_zoom._read("closeViewZoomedIn")


def test_write_failure_raises(monkeypatch):
    monkeypatch.setattr(
        os_zoom, "_defaults",
        lambda *a: subprocess.CompletedProcess(a, 1, "", "denied"),
    )
    monkeypatch.setattr(os_zoom, "is_zoomed", lambda: False)
    with pytest.raises(os_zoom.OsZoomError):
        os_zoom.zoom_in(target=2.0)
