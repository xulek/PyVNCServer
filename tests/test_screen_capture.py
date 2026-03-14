"""
Tests for screen capture pixel conversion helpers.
"""

import logging
import threading

from vnc_lib.capture_backends import CaptureFrame
from vnc_lib.screen_capture import ScreenCapture, CaptureResult


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
    cap._active_backend = "none"
    cap._dxcam_available = False
    cap._dxcam = None
    cap._mss_available = False
    cap._mss = None
    cap._pil_available = False
    cap._ImageGrab = None
    cap._Image = None
    cap._cache_ttl = 0.016
    cap.backend_preference = "auto"
    cap._backend = None
    cap._backend_registry = {}
    cap._build_backend_registry()
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


def test_get_backend_name_reports_active_backend():
    cap = _capture_without_init()
    cap._active_backend = "dxcam"
    assert cap.get_backend_name() == "dxcam"

    cap._active_backend = "mss"
    assert cap.get_backend_name() == "mss"

    cap._active_backend = "pil"
    assert cap.get_backend_name() == "pil"

    cap._active_backend = "none"
    assert cap.get_backend_name() == "none"


def test_benchmark_capture_temporarily_disables_cache_and_restores_it():
    cap = _capture_without_init()
    calls = []

    def _fake_capture_fast(_pixel_format):
        calls.append(cap._cache_ttl)
        return CaptureResult(b"x" * 16, None, 2, 2, 0.010)

    cap.capture_fast = _fake_capture_fast

    stats = cap.benchmark_capture({'bits_per_pixel': 32}, iterations=3, warmup=1)

    assert stats["backend"] == "none"
    assert stats["iterations"] == 3
    assert stats["avg_ms"] == 10.0
    assert calls == [0.0, 0.0, 0.0, 0.0]
    assert cap._cache_ttl == 0.016


def test_apply_backend_preference_selects_dxcam_when_requested():
    cap = _capture_without_init()
    cap.backend_preference = "dxcam"
    cap._dxcam_available = True

    cap._apply_backend_preference()

    assert cap._active_backend == "dxcam"


def test_dxcam_frame_to_bgra_supports_rgb_frames():
    cap = _capture_without_init()

    # RGB pixels: red, green
    frame = bytes([
        255, 0, 0,
        0, 255, 0,
    ])

    bgra = cap._dxcam_frame_to_bgra(frame, 2, 1, 3, "RGB")

    assert bgra == bytes([
        0, 0, 255, 0,
        0, 255, 0, 0,
    ])


def test_capture_frame_includes_backend_metadata():
    cap = _capture_without_init()
    cap._backend_registry = {}
    cap._backend = None
    cap.capture_fast = lambda _pixel_format: CaptureResult(b"x", None, 1, 1, 0.001)

    frame = cap.capture_frame({'bits_per_pixel': 32})

    assert isinstance(frame, CaptureFrame)
    assert frame.result.width == 1
    assert frame.metadata.backend_name == "none"
