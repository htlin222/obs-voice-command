from pathlib import Path
from obs_voice_command.config import load_config

def test_defaults_when_file_missing(tmp_path: Path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.obs.port == 4455
    assert cfg.zoom.level == 2.0
    assert cfg.zoom.deadzone == 0.15
    assert cfg.zoom.smoothing == 0.12
    # 預設指令表必須內建
    actions = {c.action for c in cfg.commands}
    assert actions == {"zoom_in", "zoom_out"}
    zi = next(c for c in cfg.commands if c.action == "zoom_in")
    assert "來個特寫" in zi.phrases

def test_partial_override(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[zoom]\nlevel = 3.0\n\n'
        '[[commands]]\nphrases = ["放大"]\naction = "zoom_in"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.zoom.level == 3.0
    assert cfg.zoom.deadzone == 0.15          # 未覆寫的用預設
    assert len(cfg.commands) == 1             # commands 整組覆寫，不合併
    assert cfg.obs.host == "localhost"

def test_invalid_action_raises(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('[[commands]]\nphrases = ["x"]\naction = "explode"\n', encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        load_config(p)
