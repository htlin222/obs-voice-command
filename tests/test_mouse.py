from obs_voice_command.mouse import DisplayInfo, locate


def test_locate_main_display():
    """Mouse at (100, 50) on main Retina display → pixel coords (200.0, 100.0)."""
    main = DisplayInfo(
        origin_x=0.0, origin_y=0.0,
        width_pts=1512.0, height_pts=982.0,
        width_px=3024, height_px=1964
    )
    external = DisplayInfo(
        origin_x=1512.0, origin_y=0.0,
        width_pts=1920.0, height_pts=1080.0,
        width_px=1920, height_px=1080
    )
    displays = [main, external]

    result = locate((100.0, 50.0), displays)
    assert result is not None
    display, px, py = result
    assert display == main
    assert px == 200.0  # (100 - 0) * (3024 / 1512)
    assert py == 100.0  # (50 - 0) * (1964 / 982)


def test_locate_external_display():
    """Mouse at (1600, 500) on external 1x display → pixel coords (88.0, 500.0)."""
    main = DisplayInfo(
        origin_x=0.0, origin_y=0.0,
        width_pts=1512.0, height_pts=982.0,
        width_px=3024, height_px=1964
    )
    external = DisplayInfo(
        origin_x=1512.0, origin_y=0.0,
        width_pts=1920.0, height_pts=1080.0,
        width_px=1920, height_px=1080
    )
    displays = [main, external]

    result = locate((1600.0, 500.0), displays)
    assert result is not None
    display, px, py = result
    assert display == external
    assert px == 88.0   # (1600 - 1512) * (1920 / 1920)
    assert py == 500.0  # (500 - 0) * (1080 / 1080)


def test_locate_no_display():
    """Mouse at (5000, 5000) is not on any display → None."""
    main = DisplayInfo(
        origin_x=0.0, origin_y=0.0,
        width_pts=1512.0, height_pts=982.0,
        width_px=3024, height_px=1964
    )
    external = DisplayInfo(
        origin_x=1512.0, origin_y=0.0,
        width_pts=1920.0, height_pts=1080.0,
        width_px=1920, height_px=1080
    )
    displays = [main, external]

    result = locate((5000.0, 5000.0), displays)
    assert result is None


def test_locate_boundary_point():
    """Mouse at origin (0, 0) belongs to main display → (0.0, 0.0)."""
    main = DisplayInfo(
        origin_x=0.0, origin_y=0.0,
        width_pts=1512.0, height_pts=982.0,
        width_px=3024, height_px=1964
    )
    external = DisplayInfo(
        origin_x=1512.0, origin_y=0.0,
        width_pts=1920.0, height_pts=1080.0,
        width_px=1920, height_px=1080
    )
    displays = [main, external]

    result = locate((0.0, 0.0), displays)
    assert result is not None
    display, px, py = result
    assert display == main
    assert px == 0.0
    assert py == 0.0


def test_locate_skips_degenerate_display():
    """寬或高為 0 的顯示器資訊不可造成除以零，應被跳過。"""
    broken = DisplayInfo(origin_x=0.0, origin_y=0.0, width_pts=0.0, height_pts=0.0,
                         width_px=0, height_px=0)
    ok = DisplayInfo(origin_x=0.0, origin_y=0.0, width_pts=100.0, height_pts=100.0,
                     width_px=200, height_px=200)
    result = locate((10.0, 10.0), [broken, ok])
    assert result is not None
    assert result[0] == ok and result[1] == 20.0
