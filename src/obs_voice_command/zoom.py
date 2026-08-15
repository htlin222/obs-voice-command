"""Zoom transform 純數學。座標單位：source 像素（除非註明 canvas）。"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Transform:
    pos_x: float
    pos_y: float
    scale_x: float
    scale_y: float


def compute_transform(
    orig: Transform,
    canvas: tuple[float, float],
    src: tuple[float, float],
    z: float,
    cx: float,
    cy: float,
) -> Transform:
    """以 source 內的點 (cx, cy) 為中心、倍率 z 計算 scene item transform。

    z=1 時回傳原始 transform。position 會 clamp 避免露出畫布外黑邊。
    """
    if math.isclose(z, 1.0):
        return orig
    sx = orig.scale_x * z
    sy = orig.scale_y * z
    cw, ch = canvas
    px = cw / 2.0 - cx * sx
    py = ch / 2.0 - cy * sy
    px = _clamp(px, cw - src[0] * sx, 0.0)
    py = _clamp(py, ch - src[1] * sy, 0.0)
    return Transform(pos_x=px, pos_y=py, scale_x=sx, scale_y=sy)


def apply_deadzone(
    cx: float, cy: float, mx: float, my: float, radius: float
) -> tuple[float, float]:
    """滑鼠 (mx,my) 在目前中心 (cx,cy) 的 deadzone 內 → 中心不動；
    在外 → 中心沿連線移到距滑鼠 radius 處（畫面追上但不過衝）。"""
    dx, dy = mx - cx, my - cy
    dist = math.hypot(dx, dy)
    if dist <= radius:
        return cx, cy
    k = (dist - radius) / dist
    return cx + dx * k, cy + dy * k


def smooth(current: float, target: float, factor: float) -> float:
    """指數平滑一步；距離 < 0.01 直接貼齊避免抖動不收斂。"""
    nxt = current + (target - current) * factor
    if abs(nxt - target) < 0.01:
        return target
    return nxt


def _clamp(v: float, lo: float, hi: float) -> float:
    if lo > hi:  # source 比 canvas 小的退化情況：置中不 clamp
        return v
    return max(lo, min(hi, v))
