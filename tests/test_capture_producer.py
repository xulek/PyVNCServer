"""Generation-aware shared capture producer tests."""

from pyvncserver.platform.producer import CaptureProducer, FrameSnapshot, NATIVE_BGR0
from vnc_lib.capture_backends import CaptureFrame, CaptureMetadata
from vnc_lib.screen_capture import CaptureResult


class _FakeCapture:
    def set_cache_frame_rate(self, _fps):
        return None

    def capture_frame(self, _pixel_format):
        raise AssertionError("capture_frame should not be called in this test")

    def convert_native_bgr0(self, pixel_data, _width, _height, _pixel_format):
        return pixel_data

    def close_current_thread_sessions(self):
        return None


def _frame(generation_marker: int, dirty_regions):
    width = 8
    height = 8
    pixels = bytes([generation_marker & 0xFF, 0, 0, 0] * width * height)
    return CaptureFrame(
        result=CaptureResult(pixels, None, width, height, 0.001),
        metadata=CaptureMetadata(
            backend_name="fake",
            dirty_regions=list(dirty_regions),
            move_rects=[],
            supports_dirty_regions=True,
            supports_move_rects=False,
        ),
    )


def test_slow_client_receives_union_of_skipped_generations():
    producer = CaptureProducer(_FakeCapture(), fps=30, history_size=8)
    first = _frame(1, [(0, 0, 2, 2)])
    second = _frame(2, [(2, 2, 2, 2)])
    third = _frame(3, [(4, 4, 2, 2)])

    producer._append_history(1, first)
    producer._append_history(2, second)
    producer._append_history(3, third)
    producer._generation = 3
    producer._snapshot = FrameSnapshot(3, third)

    snapshot = producer.get_frame(NATIVE_BGR0, since_generation=1)

    assert snapshot.generation == 3
    assert snapshot.frame.metadata.dirty_regions == [(2, 2, 2, 2), (4, 4, 2, 2)]


def test_client_at_current_generation_receives_no_dirty_pixels():
    producer = CaptureProducer(_FakeCapture(), fps=30, history_size=8)
    frame = _frame(1, [(0, 0, 8, 8)])
    producer._append_history(1, frame)
    producer._generation = 1
    producer._snapshot = FrameSnapshot(1, frame)

    snapshot = producer.get_frame(NATIVE_BGR0, since_generation=1)

    assert snapshot.frame.metadata.dirty_regions == []


def test_missing_history_falls_back_to_full_frame():
    producer = CaptureProducer(_FakeCapture(), fps=30, history_size=8)
    frame = _frame(20, [(7, 7, 1, 1)])
    producer._append_history(20, frame)
    producer._generation = 20
    producer._snapshot = FrameSnapshot(20, frame)

    snapshot = producer.get_frame(NATIVE_BGR0, since_generation=1)

    assert snapshot.frame.metadata.dirty_regions == [(0, 0, 8, 8)]
