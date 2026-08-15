import math
from obs_voice_command.zoom import (
    Transform, compute_transform, apply_deadzone, smooth,
)

# 情境：1920x1080 canvas，source 3840x2160（Retina 2x），
# 原始 transform 把 source 縮到剛好鋪滿 canvas：scale 0.5, pos (0,0)
ORIG = Transform(pos_x=0.0, pos_y=0.0, scale_x=0.5, scale_y=0.5)
CANVAS = (1920.0, 1080.0)
SRC = (3840.0, 2160.0)

def test_zoom_centers_mouse():
    # 滑鼠在 source 正中央 → zoom 後 position 應讓中央對準 canvas 中心
    t = compute_transform(ORIG, CANVAS, SRC, z=2.0, cx=1920.0, cy=1080.0)
    assert math.isclose(t.scale_x, 1.0)
    # canvas_center(960) - 1920*1.0 = -960，但 clamp 下限 = 1920-3840 = -1920 → -960 合法
    assert math.isclose(t.pos_x, -960.0)
    assert math.isclose(t.pos_y, -540.0)

def test_zoom_corner_is_clamped():
    # 滑鼠在 (0,0) 角落 → 未 clamp 會是正值（露黑邊），必須 clamp 到 0
    t = compute_transform(ORIG, CANVAS, SRC, z=2.0, cx=0.0, cy=0.0)
    assert t.pos_x == 0.0 and t.pos_y == 0.0

def test_zoom_far_corner_clamped():
    t = compute_transform(ORIG, CANVAS, SRC, z=2.0, cx=3840.0, cy=2160.0)
    assert math.isclose(t.pos_x, 1920.0 - 3840.0)   # canvas_w - src_w*scale
    assert math.isclose(t.pos_y, 1080.0 - 2160.0)

def test_z1_returns_original():
    t = compute_transform(ORIG, CANVAS, SRC, z=1.0, cx=123.0, cy=456.0)
    # z=1 時不管滑鼠在哪都應回到原始鋪滿狀態
    assert math.isclose(t.scale_x, 0.5) and math.isclose(t.pos_x, 0.0)

def test_deadzone_inside_no_move():
    assert apply_deadzone(cx=100.0, cy=100.0, mx=110.0, my=100.0, radius=50.0) == (100.0, 100.0)

def test_deadzone_outside_moves_to_edge():
    # 滑鼠在右方 100px、半徑 50 → 目標往滑鼠方向移到「距滑鼠 50」處
    cx, cy = apply_deadzone(cx=100.0, cy=100.0, mx=200.0, my=100.0, radius=50.0)
    assert math.isclose(cx, 150.0) and math.isclose(cy, 100.0)

def test_smooth_converges():
    v = 0.0
    for _ in range(200):
        v = smooth(v, 100.0, 0.12)
    assert abs(v - 100.0) < 1.0

def test_smooth_snaps_when_close():
    assert smooth(99.999, 100.0, 0.12) == 100.0   # 距離 < 0.01 直接貼齊
