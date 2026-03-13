"""
Tests for screen capture pixel conversion helpers.
"""

import logging
import threading

from vnc_lib.screen_capture import ScreenCapture


def _capture_without_init() -> ScreenCapture:
    cap = ScreenCapture.__new__(ScreenCapture)
    cap.logger = logging.getLogger("test.screen_capture")
    cap._pixel_buffer = None
    cap._palette_lut_cache = {}
    cap._numpy_lut_cache = {}
    cap._numpy_available = False
    cap._np = None
    cap._capture_lock = threading.RLock()
    cap._thread_local = threading.local()
    cap._mss_available = False
    cap._mss = None
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


def test_capture_region_uses_pil_backend_when_available():
    cap = _capture_without_init()
    cap.scale_factor = 1.0
    cap._ensure_pil = lambda: None

    class _FakeScreenshot:
        def resize(self, size, _mode):
            return self

        def convert(self, _mode):
            return self

        def tobytes(self):
            return b"pixel-data"

        @property
        def size(self):
            return (2, 2)

    class _FakeGrabber:
        @staticmethod
        def grab(*, bbox):
            assert bbox == (1, 2, 4, 6)
            return _FakeScreenshot()

    class _FakeImage:
        class Resampling:
            BILINEAR = object()

    cap._ImageGrab = _FakeGrabber()
    cap._Image = _FakeImage()
    cap._convert_to_pixel_format = lambda screenshot, pixel_format: b"converted"

    result = cap.capture_region(1, 2, 3, 4, {'bits_per_pixel': 32})

    assert result == b"converted"


def test_get_mss_session_is_thread_local():
    cap = _capture_without_init()

    class _FakeMSSModule:
        def __init__(self):
            self.created = 0

        def mss(self):
            self.created += 1
            return {'session_id': self.created}

    fake_mss = _FakeMSSModule()
    cap._mss_available = True
    cap._mss = fake_mss

    main_session_a = cap._get_mss_session()
    main_session_b = cap._get_mss_session()

    assert main_session_a is main_session_b

    thread_result = {}

    def _worker():
        thread_result['session'] = cap._get_mss_session()

    worker = threading.Thread(target=_worker)
    worker.start()
    worker.join()

    assert thread_result['session'] is not main_session_a
    assert fake_mss.created == 2
