import tomllib
from dataclasses import dataclass
from pathlib import Path


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
        if self.action not in ("zoom_in", "zoom_out"):
            raise ValueError(f"Invalid action: {self.action}")


@dataclass(frozen=True)
class Config:
    obs: ObsConfig
    zoom: ZoomConfig
    audio: AudioConfig
    commands: tuple[Command, ...]


def load_config(path: Path) -> Config:
    default_commands = (
        Command(phrases=("來個特寫", "放大一點"), action="zoom_in"),
        Command(phrases=("退回全畫面", "退出特寫", "退出", "拉遠"), action="zoom_out"),
    )

    if not path.exists():
        return Config(
            obs=ObsConfig(),
            zoom=ZoomConfig(),
            audio=AudioConfig(),
            commands=default_commands,
        )

    with open(path, "rb") as f:
        data = tomllib.load(f)

    obs_data = data.get("obs", {})
    obs = ObsConfig(
        host=obs_data.get("host", "localhost"),
        port=obs_data.get("port", 4455),
        password=obs_data.get("password", ""),
        scene=obs_data.get("scene", ""),
        source=obs_data.get("source", ""),
    )

    zoom_data = data.get("zoom", {})
    zoom = ZoomConfig(
        level=zoom_data.get("level", 2.0),
        os_level=zoom_data.get("os_level", 1.5),
        deadzone=zoom_data.get("deadzone", 0.15),
        smoothing=zoom_data.get("smoothing", 0.12),
    )

    audio_data = data.get("audio", {})
    audio = AudioConfig(
        device=audio_data.get("device", ""),
    )

    if "commands" in data:
        commands_data = data["commands"]
        commands = tuple(
            Command(
                phrases=tuple(cmd["phrases"]),
                action=cmd["action"],
            )
            for cmd in commands_data
        )
    else:
        commands = default_commands

    return Config(
        obs=obs,
        zoom=zoom,
        audio=audio,
        commands=commands,
    )
