"""PyVNCServer 4.1 low-latency regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyvncserver._core.capture_backends import CaptureFrame, CaptureMetadata
from pyvncserver._core.change_detector import AdaptiveChangeDetector
from pyvncserver._core.io_utils import recv_exact
from pyvncserver._core.metrics import ConnectionMetrics
from pyvncserver._core.protocol import RFBProtocol
from pyvncserver._core.screen_capture import CaptureResult
from pyvncserver.app.server import VNCServerV3
from pyvncserver.config import ServerSettings
from pyvncserver.platform.producer import CaptureProducer, FrameSnapshot, NATIVE_BGR0
from pyvncserver._core.exceptions import ConfigurationError


class _CountingCapture:
    def __init__(self) -> None:
        self.convert_calls = 0

    def set_cache_frame_rate(self, _fps):
        return None

    def capture_frame(self, _pixel_format):
        raise AssertionError("unexpected live capture")

    def convert_native_bgr0(self, pixel_data, _width, _height, _pixel_format):
        self.convert_calls += 1
        # Enough to prove the cache stores the converted object, not the native one.
        return bytes(reversed(pixel_data))

    def close_current_thread_sessions(self):
        return None


class _RecvIntoSocket:
    def __init__(self, payload: bytes, chunk: int = 2) -> None:
        self.payload = bytearray(payload)
        self.chunk = chunk
        self.recv_into_calls = 0
        self.recv_calls = 0

    def recv_into(self, view) -> int:
        self.recv_into_calls += 1
        if not self.payload:
            return 0
        count = min(len(view), self.chunk, len(self.payload))
        view[:count] = self.payload[:count]
        del self.payload[:count]
        return count

    def recv(self, _size: int):
        self.recv_calls += 1
        raise AssertionError("recv() fallback should not be used")


class _RecordingSocket:
    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def sendall(self, data) -> None:
        self.calls.append(bytes(data))


def _frame(marker: int = 1) -> CaptureFrame:
    width = 8
    height = 8
    pixels = bytes([marker, 2, 3, 0] * width * height)
    return CaptureFrame(
        result=CaptureResult(pixels, None, width, height, 0.001),
        metadata=CaptureMetadata(
            backend_name="fake",
            dirty_regions=[(0, 0, width, height)],
            supports_dirty_regions=True,
        ),
    )


def test_change_detector_exact_unchanged_fast_path_skips_tile_scan(monkeypatch):
    detector = AdaptiveChangeDetector(64, 64)
    first = bytes(bytearray(64 * 64 * 4))
    second = bytes(bytearray(first))  # distinct object, identical content
    detector.detect_changes(first, 4)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("tile scan should be skipped for an exactly identical frame")

    monkeypatch.setattr(detector.tile_grid, "update_and_get_changed", should_not_run)
    assert detector.detect_changes(second, 4) == []


def test_capture_producer_reuses_pixel_format_conversion_per_generation():
    capture = _CountingCapture()
    producer = CaptureProducer(capture, fps=30, conversion_cache_entries=4)
    frame = _frame(1)
    producer._generation = 7
    producer._snapshot = FrameSnapshot(7, frame, 1.0)

    rgb0 = dict(NATIVE_BGR0)
    rgb0["red_shift"] = 0
    rgb0["blue_shift"] = 16

    first = producer.get_frame(rgb0)
    second = producer.get_frame(rgb0)

    assert capture.convert_calls == 1
    assert first.frame.result.pixel_data == second.frame.result.pixel_data
    assert producer.stats["conversion_cache_hits"] == 1
    assert producer.stats["conversion_cache_misses"] == 1

    producer._generation = 8
    producer._snapshot = FrameSnapshot(8, _frame(2), 2.0)
    producer.get_frame(rgb0)
    assert capture.convert_calls == 2


def test_extract_region_full_width_and_partial_are_exact():
    server = object.__new__(VNCServerV3)
    width, height, bpp = 12, 10, 4
    pixels = bytes(range(240)) * 2
    pixels = pixels[: width * height * bpp]

    full_width = server._extract_region(pixels, width, height, 0, 2, width, 3, bpp)
    expected = pixels[2 * width * bpp : 5 * width * bpp]
    assert full_width == expected

    partial = server._extract_region(pixels, width, height, 3, 2, 5, 3, bpp)
    expected_rows = []
    for row in range(2, 5):
        start = (row * width + 3) * bpp
        expected_rows.append(pixels[start : start + 5 * bpp])
    assert partial == b"".join(expected_rows)


def test_recv_exact_uses_recv_into_when_available():
    sock = _RecvIntoSocket(b"abcdef", chunk=2)
    assert recv_exact(sock, 6) == b"abcdef"
    assert sock.recv_into_calls == 3
    assert sock.recv_calls == 0


def test_framebuffer_send_coalesce_threshold_avoids_large_payload_join():
    payload = b"x" * 200_000
    rectangle = (0, 0, 100, 100, 0, payload)

    low_latency = RFBProtocol(framebuffer_send_coalesce_bytes=64 * 1024)
    sock = _RecordingSocket()
    low_latency.send_framebuffer_update(sock, [rectangle])
    assert len(sock.calls) == 3  # update header, rectangle header, payload
    assert sock.calls[-1] == payload

    throughput = RFBProtocol(framebuffer_send_coalesce_bytes=512 * 1024)
    sock2 = _RecordingSocket()
    throughput.send_framebuffer_update(sock2, [rectangle])
    assert len(sock2.calls) == 1
    assert sock2.calls[0].endswith(payload)


def test_performance_profile_is_validated():
    with pytest.raises(ConfigurationError, match="performance.profile"):
        ServerSettings.from_mapping({"performance_profile": "turbo-magic"})


def test_latency_metrics_report_percentiles_and_stale_drops():
    metrics = ConnectionMetrics("client")
    for value_ms in (1, 2, 3, 4, 20):
        metrics.record_latency(value_ms / 1000.0, 0.0005)
    metrics.record_stale_frame_drop()

    assert metrics.producer_to_wire_p50_ms == 3.0
    assert metrics.producer_to_wire_p95_ms == 20.0
    assert metrics.producer_to_wire_p99_ms == 20.0
    assert metrics.stale_frames_dropped == 1


def test_low_latency_encoded_cache_is_skipped_for_single_client():
    server = object.__new__(VNCServerV3)
    marker = object()
    server.encoded_region_cache = marker
    server.performance_profile = "low-latency"
    server._client_registry_lock = __import__("threading").Lock()
    server._authenticated_client_sockets = {"one": object()}

    assert server._effective_encoded_region_cache() is None

    server._authenticated_client_sockets["two"] = object()
    assert server._effective_encoded_region_cache() is marker

    server.performance_profile = "balanced"
    server._authenticated_client_sockets = {"one": object()}
    assert server._effective_encoded_region_cache() is marker
