"""真 macOS 螢幕縮放（輔助使用 Zoom）：合成 Opt+Cmd 快捷鍵。

需要「系統設定 → 輔助使用 → 縮放 → 使用鍵盤快速鍵來縮放」開啟，
且執行本程式的終端機要有輔助使用權限。

機制：鍵盤縮放是在 far point (1x) 與 near point 之間切換，
跳躍目標存於 closeViewNearPoint（寫入即時生效，經實測）。
zoom_in = 先把 near point 寫成目標倍率，再按一下 Opt+Cmd+=，
macOS 用原生平滑動畫直接躍到目標；zoom_out = Opt+Cmd+8 動畫退回。
目前縮放狀態可從 closeViewZoomedIn 讀取（idle 時準確）。
"""
import subprocess
import time

import Quartz

_KEY_EQUAL = 24   # kVK_ANSI_Equal
_KEY_TOGGLE = 28  # kVK_ANSI_8
_CMD_OPT = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate
_DOMAIN = "com.apple.universalaccess"


def _key(code: int) -> None:
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(ev, _CMD_OPT)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.05)


def _read(key: str, default: float = 0.0) -> float:
    r = subprocess.run(
        ["defaults", "read", _DOMAIN, key], capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return default


def is_zoomed() -> bool:
    return _read("closeViewZoomedIn") >= 1.0


def zoom_in(target: float = 1.5) -> None:
    """設定 near point 後單按 +，原生動畫躍到 target。已縮放則冪等跳過。"""
    if is_zoomed():
        return
    for key in ("closeViewNearPoint", "closeViewDesiredZoomFactor"):
        subprocess.run(["defaults", "write", _DOMAIN, key, "-float", str(target)])
    time.sleep(0.2)  # 等 cfprefs 落盤
    _key(_KEY_EQUAL)


def zoom_out() -> None:
    """Opt+Cmd+8 動畫退回 1x。未縮放則冪等跳過（避免 toggle 反向放大）。"""
    if is_zoomed():
        _key(_KEY_TOGGLE)
