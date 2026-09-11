"""真 macOS 螢幕縮放（輔助使用 Zoom）：合成 Opt+Cmd 快捷鍵。

需要「系統設定 → 輔助使用 → 縮放 → 使用鍵盤快速鍵來縮放」開啟，
且執行本程式的終端機要有輔助使用權限。

機制：鍵盤縮放是在 far point (1x) 與 near point 之間切換，
跳躍目標存於 closeViewNearPoint（寫入即時生效，經實測）。
兩個方向都用 Opt+Cmd+8（toggle）觸發：toggle 帶平滑過場動畫，
而 Opt+Cmd+= 是步進鍵、瞬跳無動畫。zoom_in = 先把 near point 寫成
目標倍率再 toggle；zoom_out = 再 toggle 一次。
目前縮放狀態可從 closeViewZoomedIn 讀取（idle 時準確）。
"""
import math
import subprocess
import time

import Quartz

_KEY_EQUAL = 24   # kVK_ANSI_Equal
_KEY_TOGGLE = 28  # kVK_ANSI_8
_CMD_OPT = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate
_DOMAIN = "com.apple.universalaccess"
_DEFAULTS_TIMEOUT = 5.0
MAX_LEVEL = 20.0


class OsZoomError(RuntimeError):
    """呼叫 macOS 縮放失敗（權限、defaults 指令錯誤等）。"""


def _key(code: int) -> None:
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        if ev is None:
            raise OsZoomError("無法建立鍵盤事件；請確認終端機已獲得「輔助使用」權限")
        Quartz.CGEventSetFlags(ev, _CMD_OPT)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.05)


def _defaults(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["defaults", *args],
            capture_output=True, text=True, timeout=_DEFAULTS_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OsZoomError(f"執行 defaults {' '.join(args)} 失敗: {e}") from e


def _read(key: str, default: float = 0.0) -> float:
    r = _defaults("read", _DOMAIN, key)
    if r.returncode != 0:
        return default  # key 不存在（從未開過縮放）視為預設值
    try:
        return float(r.stdout.strip())
    except ValueError:
        return default


def _write_float(key: str, value: float) -> None:
    r = _defaults("write", _DOMAIN, key, "-float", repr(float(value)))
    if r.returncode != 0:
        raise OsZoomError(f"寫入 {_DOMAIN} {key} 失敗: {r.stderr.strip()}")


def is_zoomed() -> bool:
    return _read("closeViewZoomedIn") >= 1.0


def zoom_in(target: float = 1.5) -> None:
    """設定 near point 後按 toggle，平滑動畫躍到 target。已縮放則冪等跳過。"""
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        raise ValueError("zoom target 必須是數字")
    if not math.isfinite(target) or not 1.0 < target <= MAX_LEVEL:
        raise ValueError(f"zoom target 必須在 (1, {MAX_LEVEL}] 之間，收到 {target}")
    if is_zoomed():
        return
    for key in ("closeViewNearPoint", "closeViewDesiredZoomFactor"):
        _write_float(key, target)
    time.sleep(0.2)  # 等 cfprefs 落盤
    _key(_KEY_TOGGLE)


def zoom_out() -> None:
    """Opt+Cmd+8 動畫退回 1x。未縮放則冪等跳過（避免 toggle 反向放大）。"""
    if is_zoomed():
        _key(_KEY_TOGGLE)
