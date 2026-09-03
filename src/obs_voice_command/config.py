"""config.toml 載入與驗證。所有欄位都做型別與範圍檢查，錯誤訊息指出欄位名。"""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_ACTIONS = ("zoom_in", "zoom_out")


class ConfigError(ValueError):
    """設定檔格式或內容不合法。"""


@dataclass(frozen=True)
class ObsConfig:
    host: str = "localhost"
    port: int = 4455
    password: str = ""
    scene: str = ""
    source: str = ""


@dataclass(frozen=True)
class ZoomConfig:
    level: float = 2.0
    os_level: float = 1.5   # --os 模式的目標倍率（OS 全螢幕縮放體感較強，預設較小）
    deadzone: float = 0.15
    smoothing: float = 0.12


@dataclass(frozen=True)
class AudioConfig:
    device: str = ""


@dataclass(frozen=True)
class Command:
    phrases: tuple[str, ...]
    action: str

    def __post_init__(self):
        if self.action not in VALID_ACTIONS:
            raise ConfigError(f"Invalid action: {self.action}")
        if not self.phrases or any(not isinstance(p, str) or not p.strip() for p in self.phrases):
            raise ConfigError(f"commands[{self.action}].phrases 必須是非空字串陣列")


@dataclass(frozen=True)
class Config:
    obs: ObsConfig
    zoom: ZoomConfig
    audio: AudioConfig
    commands: tuple[Command, ...]


DEFAULT_COMMANDS = (
    Command(phrases=("來個特寫", "放大一點"), action="zoom_in"),
    Command(phrases=("退回全畫面", "退出特寫", "退出", "拉遠"), action="zoom_out"),
)


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    t = data.get(name, {})
    if not isinstance(t, dict):
        raise ConfigError(f"[{name}] 必須是一個表格（table）")
    return t


def _str(t: dict[str, Any], key: str, default: str, *, section: str) -> str:
    v = t.get(key, default)
    if not isinstance(v, str):
        raise ConfigError(f"{section}.{key} 必須是字串")
    return v


def _int(t: dict[str, Any], key: str, default: int, *, section: str, lo: int, hi: int) -> int:
    v = t.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigError(f"{section}.{key} 必須是整數")
    if not lo <= v <= hi:
        raise ConfigError(f"{section}.{key} 必須介於 {lo} 與 {hi} 之間")
    return v


def _float(
    t: dict[str, Any], key: str, default: float, *, section: str,
    lo: float, hi: float, lo_exclusive: bool = False,
) -> float:
    v = t.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{section}.{key} 必須是數字")
    v = float(v)
    if not math.isfinite(v):
        raise ConfigError(f"{section}.{key} 必須是有限數值")
    below = v <= lo if lo_exclusive else v < lo
    if below or v > hi:
        rel = ">" if lo_exclusive else ">="
        raise ConfigError(f"{section}.{key} 必須 {rel} {lo} 且 <= {hi}")
    return v


def _parse_commands(raw: Any) -> tuple[Command, ...]:
    if not isinstance(raw, list):
        raise ConfigError("commands 必須是 [[commands]] 陣列")
    out = []
    for i, cmd in enumerate(raw):
        if not isinstance(cmd, dict):
            raise ConfigError(f"commands[{i}] 必須是表格")
        phrases = cmd.get("phrases")
        action = cmd.get("action")
        if not isinstance(phrases, list):
            raise ConfigError(f"commands[{i}].phrases 必須是字串陣列")
        if not isinstance(action, str):
            raise ConfigError(f"commands[{i}].action 必須是字串（{'/'.join(VALID_ACTIONS)}）")
        out.append(Command(phrases=tuple(phrases), action=action))
    if not out:
        raise ConfigError("commands 不可為空；要用預設指令請整段移除")
    return tuple(out)


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config(
            obs=ObsConfig(),
            zoom=ZoomConfig(),
            audio=AudioConfig(),
            commands=DEFAULT_COMMANDS,
        )

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} 不是合法的 TOML: {e}") from e
    except OSError as e:
        raise ConfigError(f"無法讀取 {path}: {e}") from e

    obs_data = _table(data, "obs")
    obs = ObsConfig(
        host=_str(obs_data, "host", "localhost", section="obs") or "localhost",
        port=_int(obs_data, "port", 4455, section="obs", lo=1, hi=65535),
        password=_str(obs_data, "password", "", section="obs"),
        scene=_str(obs_data, "scene", "", section="obs"),
        source=_str(obs_data, "source", "", section="obs"),
    )

    zoom_data = _table(data, "zoom")
    zoom = ZoomConfig(
        # 倍率 <= 1 會讓 zoom_in / zoom_out 狀態機永遠卡住
        level=_float(zoom_data, "level", 2.0, section="zoom", lo=1.0, hi=20.0, lo_exclusive=True),
        os_level=_float(zoom_data, "os_level", 1.5, section="zoom", lo=1.0, hi=20.0, lo_exclusive=True),
        deadzone=_float(zoom_data, "deadzone", 0.15, section="zoom", lo=0.0, hi=1.0),
        # smoothing=0 永不收斂、>1 會震盪發散
        smoothing=_float(zoom_data, "smoothing", 0.12, section="zoom", lo=0.0, hi=1.0, lo_exclusive=True),
    )

    audio_data = _table(data, "audio")
    audio = AudioConfig(
        device=_str(audio_data, "device", "", section="audio"),
    )

    if "commands" in data:
        commands = _parse_commands(data["commands"])
    else:
        commands = DEFAULT_COMMANDS

    return Config(
        obs=obs,
        zoom=zoom,
        audio=audio,
        commands=commands,
    )
