"""
Targeted unit tests for the packaged VNC server runtime.
"""

import struct
import socket
import threading
import logging

from vnc_lib.cursor import CursorData
from vnc_lib.protocol import RFBProtocol
from vnc_lib.server_utils import NetworkProfile
from pyvncserver import VNCServerV3


def _server_without_init() -> VNCServerV3:
    """Create server instance without opening sockets."""
    server = VNCServerV3.__new__(VNCServerV3)
    server.input_control_policy = 'single-controller'
    server._input_control_lock = threading.Lock()
    server._input_controller_client_id = None
    server._input_control_rejections_logged = set()
    server._client_registry_lock = threading.Lock()
    server._authenticated_client_sockets = {}
    server.logger = logging.getLogger("test.vnc_server")
    return server


def _native_bgr0_pixel_format() -> dict:
    return {
        'bits_per_pixel': 32,
        'depth': 24,
        'big_endian_flag': 0,
        'true_colour_flag': 1,
        'red_max': 255,
        'green_max': 255,
        'blue_max': 255,
        'red_shift': 16,
        'green_shift': 8,
        'blue_shift': 0,
    }


class _FakeCursorCapture:
    def __init__(self, cursor_data: CursorData | None, pointer_pos: tuple[int, int] | None):
        self._cursor_data = cursor_data
        self._pointer_pos = pointer_pos

    def capture_cursor(self) -> CursorData | None:
        return self._cursor_data

    def get_pointer_position(self) -> tuple[int, int] | None:
        return self._pointer_pos


class _FakeCursorEncoder:
    def __init__(self, changed: bool, encoded: bytes = b"cursor"):
        self.changed = changed
        self.encoded = encoded

    def has_cursor_changed(self, cursor_data: CursorData) -> bool:
        return self.changed

    def encode_cursor(self, cursor_data: CursorData, bytes_per_pixel: int = 4):
        return cursor_data.hotspot_x, cursor_data.hotspot_y, self.encoded


def test_normalize_request_region_clamps_to_framebuffer():
    server = _server_without_init()

    region = server._normalize_request_region(
        {'x': 100, 'y': 100, 'width': 500, 'height': 500},
        fb_width=300,
        fb_height=200,
    )

    assert region == (100, 100, 200, 100)


def test_build_cursor_pseudo_rectangles_sends_cursor_and_pointer_pos():
    server = _server_without_init()
    server.enable_cursor_encoding = True
    protocol = RFBProtocol()
    cursor_data = CursorData(
        width=16,
        height=16,
        hotspot_x=3,
        hotspot_y=4,
        pixel_data=b"\x00\x00\x00\xff" * 16 * 16,
        bitmask=b"\xff" * (16 * 16),
    )

    rectangles, last_pointer_pos = server._build_cursor_pseudo_rectangles(
        protocol,
        [protocol.ENCODING_CURSOR, protocol.ENCODING_POINTER_POS],
        _native_bgr0_pixel_format(),
        _FakeCursorCapture(cursor_data, (120, 80)),
        _FakeCursorEncoder(changed=True, encoded=b"encoded-cursor"),
        None,
    )

    assert rectangles == [
        (3, 4, 16, 16, protocol.ENCODING_CURSOR, b"encoded-cursor"),
        (120, 80, 0, 0, protocol.ENCODING_POINTER_POS, b""),
    ]
    assert last_pointer_pos == (120, 80)


def test_build_cursor_pseudo_rectangles_suppresses_unchanged_updates():
    server = _server_without_init()
    server.enable_cursor_encoding = True
    protocol = RFBProtocol()
    cursor_data = CursorData(
        width=8,
        height=8,
        hotspot_x=0,
        hotspot_y=0,
        pixel_data=b"\xff\xff\xff\xff" * 64,
        bitmask=b"\xff" * 64,
    )

    rectangles, last_pointer_pos = server._build_cursor_pseudo_rectangles(
        protocol,
        [protocol.ENCODING_CURSOR, protocol.ENCODING_POINTER_POS],
        _native_bgr0_pixel_format(),
        _FakeCursorCapture(cursor_data, (10, 10)),
        _FakeCursorEncoder(changed=False),
        (10, 10),
    )

    assert rectangles == []
    assert last_pointer_pos == (10, 10)


def test_normalize_request_region_rejects_invalid():
    server = _server_without_init()

    assert server._normalize_request_region(
        {'x': 0, 'y': 0, 'width': 0, 'height': 10},
        fb_width=100,
        fb_height=100,
    ) is None
    assert server._normalize_request_region(
        {'x': 200, 'y': 0, 'width': 10, 'height': 10},
        fb_width=100,
        fb_height=100,
    ) is None


def test_intersect_regions_filters_to_request_rectangle():
    server = _server_without_init()

    regions = [(0, 0, 50, 50), (60, 60, 20, 20), (200, 200, 10, 10)]
    request = (25, 25, 40, 40)

    filtered = server._intersect_regions(regions, request)

    assert filtered == [(25, 25, 25, 25), (60, 60, 5, 5)]


def test_collapse_regions_to_bounding_box():
    server = _server_without_init()

    collapsed = server._collapse_regions_to_bounding_box(
        [(10, 10, 20, 20), (40, 30, 10, 15), (5, 8, 4, 6)]
    )

    assert collapsed == [(5, 8, 45, 37)]


def test_collapse_regions_to_bounding_box_handles_single_region():
    server = _server_without_init()

    collapsed = server._collapse_regions_to_bounding_box([(10, 10, 20, 20)])

    assert collapsed == [(10, 10, 20, 20)]


def test_should_delay_tight_for_ultravnc_by_request_count():
    server = _server_without_init()
    server.ultravnc_tight_warmup_requests = 5
    server.ultravnc_tight_warmup_seconds = 0.0

    assert server._should_delay_tight_for_ultravnc(
        ultravnc_like_client=True,
        fburq_count=3,
        first_fburq_time=10.0,
        now=11.0,
    ) is True
    assert server._should_delay_tight_for_ultravnc(
        ultravnc_like_client=True,
        fburq_count=6,
        first_fburq_time=10.0,
        now=11.0,
    ) is False


def test_should_delay_tight_for_ultravnc_by_time_window():
    server = _server_without_init()
    server.ultravnc_tight_warmup_requests = 0
    server.ultravnc_tight_warmup_seconds = 2.0

    assert server._should_delay_tight_for_ultravnc(
        ultravnc_like_client=True,
        fburq_count=50,
        first_fburq_time=100.0,
        now=101.5,
    ) is True
    assert server._should_delay_tight_for_ultravnc(
        ultravnc_like_client=True,
        fburq_count=50,
        first_fburq_time=100.0,
        now=102.1,
    ) is False


def test_should_delay_tight_for_ultravnc_false_for_non_ultravnc():
    server = _server_without_init()
    server.ultravnc_tight_warmup_requests = 50
    server.ultravnc_tight_warmup_seconds = 10.0

    assert server._should_delay_tight_for_ultravnc(
        ultravnc_like_client=False,
        fburq_count=1,
        first_fburq_time=0.0,
        now=0.1,
    ) is False


def test_extract_region_handles_bounds_safely():
    server = _server_without_init()
    pixel_data = bytes(range(12))  # 4x3, bpp=1

    region = server._extract_region(
        pixel_data,
        fb_width=4,
        fb_height=3,
        x=2,
        y=1,
        width=3,  # Extends beyond right edge; should be clamped.
        height=2,
        bytes_per_pixel=1,
    )

    assert region == bytes([6, 7, 10, 11])
    assert server._extract_region(
        pixel_data,
        fb_width=4,
        fb_height=3,
        x=5,
        y=0,
        width=1,
        height=1,
        bytes_per_pixel=1,
    ) == b''


def test_coalesce_pointer_events_keeps_latest():
    server = _server_without_init()
    protocol = RFBProtocol()
    initial = {'button_mask': 0, 'x': 10, 'y': 10}

    # Two queued move-only PointerEvent messages (type byte + 5-byte payload each):
    # (0, 20, 30) then (0, 40, 50)
    queued = (
        bytes([protocol.MSG_POINTER_EVENT]) + struct.pack(">BHH", 0, 20, 30) +
        bytes([protocol.MSG_POINTER_EVENT]) + struct.pack(">BHH", 0, 40, 50)
    )
    sock = _FakeSocket(queued)
    sock.settimeout(5.0)

    latest = server._coalesce_pointer_events(sock, protocol, initial)

    assert latest == {'button_mask': 0, 'x': 40, 'y': 50}
    assert sock.gettimeout() == 5.0


def test_coalesce_pointer_events_preserves_button_transition():
    server = _server_without_init()
    protocol = RFBProtocol()
    initial = {'button_mask': 0, 'x': 10, 'y': 10}

    queued = (
        bytes([protocol.MSG_POINTER_EVENT]) + struct.pack(">BHH", 0, 20, 30) +
        bytes([protocol.MSG_POINTER_EVENT]) + struct.pack(">BHH", 1, 40, 50)
    )
    sock = _FakeSocket(queued)
    sock.settimeout(5.0)

    latest = server._coalesce_pointer_events(sock, protocol, initial)

    assert latest == {'button_mask': 0, 'x': 20, 'y': 30}
    remaining = sock.recv(6)
    assert remaining == bytes([protocol.MSG_POINTER_EVENT]) + struct.pack(">BHH", 1, 40, 50)


def test_coalesce_framebuffer_requests_keeps_latest():
    server = _server_without_init()
    protocol = RFBProtocol()
    first = {'incremental': 1, 'x': 0, 'y': 0, 'width': 100, 'height': 100}

    queued = (
        bytes([protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST]) + struct.pack(">BHHHH", 1, 10, 20, 300, 200) +
        bytes([protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST]) + struct.pack(">BHHHH", 0, 50, 60, 640, 480)
    )
    sock = _FakeSocket(queued)
    sock.settimeout(7.0)

    latest = server._coalesce_framebuffer_update_requests(sock, protocol, first)

    assert latest == {'incremental': 0, 'x': 50, 'y': 60, 'width': 640, 'height': 480}
    assert sock.gettimeout() == 7.0


def test_select_encoder_for_update_prefers_first_client_encoding():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object(), 21: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [21, 6, 0],
        NetworkProfile.LAN,
        width=200,
        height=120,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=4,
        pixel_format=_native_bgr0_pixel_format(),
    )
    assert enc_type == 21


def test_select_encoder_for_update_skips_first_incompatible_encoding():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object(), 21: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [21, 6, 0],
        NetworkProfile.LAN,
        width=1600,
        height=900,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=2,
        pixel_format={
            **_native_bgr0_pixel_format(),
            'bits_per_pixel': 16,
            'depth': 16,
            'red_max': 31,
            'green_max': 63,
            'blue_max': 31,
            'red_shift': 11,
            'green_shift': 5,
            'blue_shift': 0,
        },
    )
    assert enc_type == 6


def test_select_encoder_for_update_respects_client_order_for_tight_over_zlib():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object(), 7: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [7, 6, 0],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=4,
        pixel_format=_native_bgr0_pixel_format(),
    )
    assert enc_type == 7


def test_select_encoder_for_update_respects_client_order_for_zlib_over_tight():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object(), 7: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [6, 7, 0],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=4,
        pixel_format=_native_bgr0_pixel_format(),
    )
    assert enc_type == 6


def test_select_encoder_for_update_allows_tight_for_ultravnc_like_client():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object(), 7: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [7, 6, 0, 9, 10],  # UltraVNC-like (9/10 present)
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=4,
        pixel_format=_native_bgr0_pixel_format(),
    )
    assert enc_type == 7


def test_select_encoder_for_update_respects_allow_jpeg_false():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object(), 21: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [21, 6, 0],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        allow_jpeg=False,
        bytes_per_pixel=4,
        pixel_format=_native_bgr0_pixel_format(),
    )
    assert enc_type == 6


def test_select_encoder_for_update_respects_allow_zlib_false():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 6: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [6, 0],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        allow_zlib=False,
        bytes_per_pixel=4,
        pixel_format=_native_bgr0_pixel_format(),
    )
    assert enc_type == 0


def test_select_encoder_for_update_falls_back_to_raw_when_client_list_has_no_usable_encoding():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 21: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [21],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=2,
        pixel_format={
            **_native_bgr0_pixel_format(),
            'bits_per_pixel': 16,
            'depth': 16,
            'red_max': 31,
            'green_max': 63,
            'blue_max': 31,
            'red_shift': 11,
            'green_shift': 5,
            'blue_shift': 0,
        },
    )
    assert enc_type == 0


def test_select_encoder_for_update_falls_back_to_rre_without_raw():
    server = _server_without_init()
    manager = _DummyEncoderManager({2: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [2],
        NetworkProfile.LAN,
        width=200,
        height=150,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
    )
    assert enc_type == 2


def test_select_encoder_for_update_keeps_order_when_low_bpp_filters_out_jpeg():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 21: object(), 2: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [21, 2, 0],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=1,
    )
    assert enc_type == 2


def test_select_encoder_for_update_lan_does_not_use_jpeg_for_16bpp():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 21: object(), 2: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        [21, 2, 0],
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=2,
    )
    assert enc_type == 2


def test_adjust_lan_jpeg_quality_reacts_to_timing():
    server = _server_without_init()
    server.lan_jpeg_quality_min = 55
    server.lan_jpeg_quality_max = 90

    lowered = server._adjust_lan_jpeg_quality(
        current_quality=75,
        frame_time=0.080,
        encoded_bytes=60000,
        original_bytes=200000,
        target_frame_time=1.0 / 30.0,
    )
    raised = server._adjust_lan_jpeg_quality(
        current_quality=lowered,
        frame_time=0.012,
        encoded_bytes=30000,
        original_bytes=200000,
        target_frame_time=1.0 / 30.0,
    )

    assert lowered < 75
    assert raised >= lowered


def test_configure_tight_compatibility_for_ultravnc_like_client():
    server = _server_without_init()
    tight = _TightModeRecorder()
    manager = _DummyEncoderManager({7: tight})

    server._configure_tight_compatibility(manager, {0, 7, 9, 10})
    assert tight.enabled_values[-1] is True

    server._configure_tight_compatibility(manager, {0, 7, 16})
    assert tight.enabled_values[-1] is False


def test_supported_pixel_format_accepts_common_32bit_true_color():
    server = _server_without_init()

    assert server._is_supported_pixel_format({
        'bits_per_pixel': 32,
        'depth': 24,
        'big_endian_flag': 0,
        'true_colour_flag': 1,
        'red_max': 255,
        'green_max': 255,
        'blue_max': 255,
        'red_shift': 16,
        'green_shift': 8,
        'blue_shift': 0,
    }) is True


def test_supported_pixel_format_rejects_big_endian():
    server = _server_without_init()

    assert server._is_supported_pixel_format({
        'bits_per_pixel': 32,
        'depth': 24,
        'big_endian_flag': 1,
        'true_colour_flag': 1,
        'red_max': 255,
        'green_max': 255,
        'blue_max': 255,
        'red_shift': 16,
        'green_shift': 8,
        'blue_shift': 0,
    }) is False


def test_encoding_supported_for_pixel_format_disables_non_compliant_encodings():
    server = _server_without_init()

    assert server._encoding_supported_for_pixel_format(1, _native_bgr0_pixel_format()) is False
    assert server._encoding_supported_for_pixel_format(16, _native_bgr0_pixel_format()) is False
    assert server._encoding_supported_for_pixel_format(7, _native_bgr0_pixel_format()) is True
    assert server._encoding_supported_for_pixel_format(7, {
        **_native_bgr0_pixel_format(),
        'red_shift': 0,
        'blue_shift': 16,
    }) is False


def test_filter_encodings_for_pixel_format_drops_incompatible_tight_and_jpeg():
    server = _server_without_init()
    manager = _DummyEncoderManager({0: object(), 7: object(), 21: object()})

    filtered, dropped = server._filter_encodings_for_pixel_format(
        [0, 7, 21, -223],
        manager,
        {
            **_native_bgr0_pixel_format(),
            'red_shift': 0,
            'blue_shift': 16,
        },
    )

    assert filtered == [0, -223]
    assert dropped == [7, 21]


def test_disconnect_other_authenticated_clients_keeps_requesting_client():
    server = _server_without_init()
    keeper = _DisconnectRecorder()
    other = _DisconnectRecorder()

    server._register_authenticated_client_socket("keep", keeper)
    server._register_authenticated_client_socket("other", other)
    server._disconnect_other_authenticated_clients("keep")

    assert keeper.closed is False
    assert other.closed is True
    assert other.shutdown_calls == [socket.SHUT_RDWR]


def test_log_selected_encoding_emits_info_message(caplog):
    server = _server_without_init()

    with caplog.at_level(logging.INFO, logger="test.vnc_server"):
        server._log_selected_encoding(7, "desktop")

    assert "Selected encoding: Tight (7) for content type: desktop" in caplog.text


def test_log_selected_region_encodings_emits_info_summary(caplog):
    server = _server_without_init()

    with caplog.at_level(logging.INFO, logger="test.vnc_server"):
        server._log_selected_region_encodings([7, 0, 7, 6])

    assert "Selected region encodings: Raw (0) x1, Zlib (6) x1, Tight (7) x2" in caplog.text


def test_try_acquire_input_control_assigns_single_controller():
    server = _server_without_init()

    assert server._try_acquire_input_control("client-a") is True
    assert server._try_acquire_input_control("client-a") is True
    assert server._try_acquire_input_control("client-b") is False


def test_release_input_control_allows_next_client():
    server = _server_without_init()

    assert server._try_acquire_input_control("client-a") is True
    server._release_input_control("client-a")

    assert server._try_acquire_input_control("client-b") is True


def test_parallel_safe_encoding_whitelist():
    server = _server_without_init()

    assert server._is_parallel_safe_encoding(0) is True
    assert server._is_parallel_safe_encoding(2) is True
    assert server._is_parallel_safe_encoding(5) is True
    assert server._is_parallel_safe_encoding(6) is False
    assert server._is_parallel_safe_encoding(7) is False
    assert server._is_parallel_safe_encoding(16) is False


class _FakeSocket:
    """Socket-like object for MSG_PEEK tests."""

    MSG_PEEK = socket.MSG_PEEK

    def __init__(self, incoming: bytes):
        self._incoming = bytearray(incoming)
        self._timeout = None

    def recv(self, n, flags=0):
        if flags == self.MSG_PEEK:
            return bytes(self._incoming[:n])
        if not self._incoming:
            return b''
        data = bytes(self._incoming[:n])
        del self._incoming[:n]
        return data

    def settimeout(self, value):
        self._timeout = value

    def gettimeout(self):
        return self._timeout


class _DummyEncoderManager:
    def __init__(self, encoders):
        self.encoders = encoders

    def get_best_encoder(self, client_encodings, content_type="default"):
        for enc in client_encodings:
            if enc in self.encoders:
                return enc, self.encoders[enc]
        if 0 in self.encoders:
            return 0, self.encoders[0]
        first_key = next(iter(self.encoders))
        return first_key, self.encoders[first_key]


class _TightModeRecorder:
    def __init__(self):
        self.enabled_values = []

    def set_stream_reset_mode(self, enabled):
        self.enabled_values.append(bool(enabled))


class _DisconnectRecorder:
    def __init__(self):
        self.closed = False
        self.shutdown_calls = []

    def shutdown(self, how):
        self.shutdown_calls.append(how)

    def close(self):
        self.closed = True
