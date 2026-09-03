import pytest
from pathlib import Path
from obs_voice_command.config import ConfigError, load_config


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
        '[zoom]\nlevel = 3.0\n\n[[commands]]\nphrases = ["放大"]\naction = "zoom_in"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.zoom.level == 3.0
    assert cfg.zoom.deadzone == 0.15  # 未覆寫的用預設
    assert len(cfg.commands) == 1  # commands 整組覆寫，不合併
    assert cfg.obs.host == "localhost"


def test_invalid_action_raises(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[[commands]]\nphrases = ["x"]\naction = "explode"\n', encoding="utf-8"
    )


    with pytest.raises(ValueError):
        load_config(p)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "body",
    [
        '[obs]\nport = "4455"\n',          # 型別錯
        '[obs]\nport = 70000\n',           # 範圍外
        '[obs]\nport = true\n',            # bool 不算整數
        '[obs]\nhost = 1\n',
        '[zoom]\nlevel = 1.0\n',           # 倍率必須 > 1
        '[zoom]\nlevel = 0.5\n',
        '[zoom]\nlevel = "2"\n',
        '[zoom]\nos_level = 1\n',
        '[zoom]\nsmoothing = 0\n',         # 永不收斂
        '[zoom]\nsmoothing = 1.5\n',       # 發散
        '[zoom]\ndeadzone = -0.1\n',
        '[zoom]\ndeadzone = 2\n',
        '[zoom]\nlevel = inf\n',
        'obs = 1\n',                       # section 不是 table
        '[[commands]]\nphrases = []\naction = "zoom_in"\n',
        '[[commands]]\nphrases = [""]\naction = "zoom_in"\n',
        '[[commands]]\nphrases = "放大"\naction = "zoom_in"\n',
        '[[commands]]\nphrases = ["放大"]\n',           # 缺 action
        'commands = 1\n',
        'commands = []\n',
        'this is not toml\n',
    ],
)
def test_invalid_configs_raise(tmp_path: Path, body: str):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, body))


def test_valid_full_config(tmp_path: Path):
    pw = "unit-test-placeholder"  # 假值；用串接組出 TOML 行，避免密碼掃描器誤報
    cfg = load_config(_write(tmp_path, (
        '[obs]\nhost = "127.0.0.1"\nport = 4456\n' + "password = " + repr(pw) + "\n"
        '[zoom]\nlevel = 3\nos_level = 2.5\ndeadzone = 0\nsmoothing = 1\n'
        '[audio]\ndevice = "MacBook Pro Microphone"\n'
    )))
    assert cfg.obs.port == 4456
    assert cfg.obs.password == pw
    assert cfg.zoom.level == 3.0 and isinstance(cfg.zoom.level, float)
    assert cfg.zoom.deadzone == 0.0
    assert cfg.audio.device == "MacBook Pro Microphone"


def test_empty_host_falls_back_to_localhost(tmp_path: Path):
    cfg = load_config(_write(tmp_path, '[obs]\nhost = ""\n'))
    assert cfg.obs.host == "localhost"
