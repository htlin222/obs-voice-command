"""macOS mouse position and multi-display layout via Quartz."""
from __future__ import annotations

from dataclasses import dataclass

import Quartz


@dataclass(frozen=True)
class DisplayInfo:
    origin_x: float
    origin_y: float
    width_pts: float
    height_pts: float
    width_px: int
    height_px: int


def get_displays() -> list[DisplayInfo]:
    """Fetch all active displays with origin, size in points, and pixel dimensions.

    Uses Quartz global coordinates (top-left origin, y-down) to match get_mouse_pos().
    """
    err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    displays = []
    for did in ids[:count]:
        b = Quartz.CGDisplayBounds(did)
        displays.append(DisplayInfo(
            origin_x=float(b.origin.x),
            origin_y=float(b.origin.y),
            width_pts=float(b.size.width),
            height_pts=float(b.size.height),
            width_px=int(Quartz.CGDisplayPixelsWide(did)),
            height_px=int(Quartz.CGDisplayPixelsHigh(did)),
        ))
    return displays


def get_mouse_pos() -> tuple[float, float]:
    """Get current mouse position in points (global coordinate system, origin top-left)."""
    ev = Quartz.CGEventCreate(None)
    loc = Quartz.CGEventGetLocation(ev)
    return (float(loc.x), float(loc.y))


def locate(
    pos: tuple[float, float],
    displays: list[DisplayInfo]
) -> tuple[DisplayInfo, float, float] | None:
    """Find which display contains position (in points), return pixel coordinates within display.

    Containment: origin_x <= x < origin_x + width_pts (same for y).
    Pixel scaling: (pos - origin) * (width_px / width_pts).
    Returns (display, pixel_x, pixel_y) or None if not on any display.
    """
    x, y = pos

    for display in displays:
        x_in_bounds = display.origin_x <= x < display.origin_x + display.width_pts
        y_in_bounds = display.origin_y <= y < display.origin_y + display.height_pts

        if x_in_bounds and y_in_bounds:
            # Convert to pixel coordinates within this display
            rel_x = x - display.origin_x
            rel_y = y - display.origin_y

            x_scale = display.width_px / display.width_pts
            y_scale = display.height_px / display.height_pts

            pixel_x = rel_x * x_scale
            pixel_y = rel_y * y_scale

            return (display, pixel_x, pixel_y)

    return None
