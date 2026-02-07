"""
Tests for screen capture pixel conversion helpers.
"""

from vnc_lib.screen_capture import ScreenCapture


def _capture_without_init() -> ScreenCapture:
    cap = ScreenCapture.__new__(ScreenCapture)
    cap._pixel_buffer = None
    cap._palette_lut_cache = {}
    cap._numpy_lut_cache = {}
    cap._numpy_available = False
    cap._np = None
    return cap


def test_convert_bgra_to_8bit_true_color_fast_path():
    cap = _capture_without_init()
    # Two pixels in BGRA: red then green
    bgra = bytes([
        0, 0, 255, 0,   # red
        0, 255, 0, 0,   # green
    ])
    pixel_format = {
        'bits_per_pixel': 8,
        'depth': 6,
        'true_colour_flag': 1,
        'big_endian_flag': 0,
        'red_max': 3,
        'green_max': 3,
        'blue_max': 3,
        'red_shift': 4,
        'green_shift': 2,
        'blue_shift': 0,
    }

    out = cap._convert_bgra_to_pixel_format(bgra, 2, 1, 2, pixel_format)

    assert out == bytes([0x30, 0x0C])


def test_convert_bgra_to_8bit_true_color_uses_lut_cache():
    cap = _capture_without_init()
    bgra = bytes([255, 0, 0, 0])
    pixel_format = {
        'bits_per_pixel': 8,
        'depth': 6,
        'true_colour_flag': 1,
        'big_endian_flag': 0,
        'red_max': 3,
        'green_max': 3,
        'blue_max': 3,
        'red_shift': 4,
        'green_shift': 2,
        'blue_shift': 0,
    }

    out1 = cap._convert_bgra_to_pixel_format(bgra, 1, 1, 1, pixel_format)
    out2 = cap._convert_bgra_to_pixel_format(bgra, 1, 1, 1, pixel_format)

    assert out1 == out2
    assert len(cap._palette_lut_cache) == 1
