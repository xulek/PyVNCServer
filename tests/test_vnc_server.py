"""
Targeted unit tests for VNCServerV3 helper logic.
"""

import struct
import socket

from vnc_lib.protocol import RFBProtocol
from vnc_lib.server_utils import NetworkProfile
from vnc_server import VNCServerV3


def _server_without_init() -> VNCServerV3:
    """Create server instance without opening sockets."""
    return VNCServerV3.__new__(VNCServerV3)


def test_normalize_request_region_clamps_to_framebuffer():
    server = _server_without_init()

    region = server._normalize_request_region(
        {'x': 100, 'y': 100, 'width': 500, 'height': 500},
        fb_width=300,
        fb_height=200,
    )

    assert region == (100, 100, 200, 100)


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


def test_select_encoder_for_update_lan_prefers_raw_for_small_rectangles():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_raw_area_threshold = 0.12
    server.lan_raw_max_pixels = 65536
    server.lan_jpeg_area_threshold = 0.25
    server.lan_jpeg_min_pixels = 32768

    manager = _DummyEncoderManager({0: object(), 16: object(), 21: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 16, 21},
        NetworkProfile.LAN,
        width=200,
        height=120,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
    )
    assert enc_type == 0


def test_select_encoder_for_update_lan_prefers_jpeg_for_large_rectangles():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_raw_area_threshold = 0.12
    server.lan_raw_max_pixels = 65536
    server.lan_jpeg_area_threshold = 0.25
    server.lan_jpeg_min_pixels = 32768

    manager = _DummyEncoderManager({0: object(), 16: object(), 21: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 16, 21},
        NetworkProfile.LAN,
        width=1600,
        height=900,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
    )
    assert enc_type == 21


def test_select_encoder_for_update_lan_prefers_tight_for_large_rectangles():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_prefer_zlib = True
    server.lan_zlib_area_threshold = 0.20
    server.lan_zlib_min_pixels = 131072
    server.lan_raw_area_threshold = 0.12
    server.lan_raw_max_pixels = 65536
    server.lan_jpeg_area_threshold = 0.95
    server.lan_jpeg_min_pixels = 9999999

    manager = _DummyEncoderManager({0: object(), 6: object(), 7: object(), 16: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 6, 7, 16},
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        prefer_zlib_override=True,
        bytes_per_pixel=4,
    )
    assert enc_type == 7


def test_select_encoder_for_update_lan_falls_back_to_zlib_without_tight():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_prefer_zlib = True
    server.lan_zlib_area_threshold = 0.20
    server.lan_zlib_min_pixels = 131072
    server.lan_raw_area_threshold = 0.12
    server.lan_raw_max_pixels = 65536
    server.lan_jpeg_area_threshold = 0.95
    server.lan_jpeg_min_pixels = 9999999

    manager = _DummyEncoderManager({0: object(), 6: object(), 16: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 6, 16},
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        prefer_zlib_override=True,
        bytes_per_pixel=4,
    )
    assert enc_type == 6


def test_select_encoder_for_update_lan_does_not_use_zlib_for_low_bpp():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_prefer_zlib = True
    server.lan_zlib_area_threshold = 0.20
    server.lan_zlib_min_pixels = 131072
    server.lan_raw_area_threshold = 0.01
    server.lan_raw_max_pixels = 10
    server.lan_jpeg_area_threshold = 0.95
    server.lan_jpeg_min_pixels = 9999999

    manager = _DummyEncoderManager({0: object(), 6: object(), 16: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 6, 16},
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        prefer_zlib_override=True,
        bytes_per_pixel=1,
    )
    assert enc_type == 0


def test_select_encoder_for_update_lan_respects_zlib_override_false():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_prefer_zlib = True
    server.lan_zlib_area_threshold = 0.20
    server.lan_zlib_min_pixels = 131072
    server.lan_raw_area_threshold = 0.01
    server.lan_raw_max_pixels = 10
    server.lan_jpeg_area_threshold = 0.95
    server.lan_jpeg_min_pixels = 9999999

    manager = _DummyEncoderManager({0: object(), 6: object(), 16: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 6, 16},
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        prefer_zlib_override=False,
        bytes_per_pixel=4,
    )
    assert enc_type == 0


def test_select_encoder_for_update_lan_zlib_respects_area_threshold():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_prefer_zlib = True
    server.lan_zlib_area_threshold = 0.20
    server.lan_zlib_min_pixels = 4096
    server.lan_raw_area_threshold = 0.01
    server.lan_raw_max_pixels = 10
    server.lan_jpeg_area_threshold = 0.95
    server.lan_jpeg_min_pixels = 9999999

    manager = _DummyEncoderManager({0: object(), 6: object(), 7: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 6, 7},
        NetworkProfile.LAN,
        width=250,
        height=200,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        prefer_zlib_override=True,
        bytes_per_pixel=4,
    )
    assert enc_type == 0


def test_select_encoder_for_update_lan_raw_cap_prefers_raw():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_raw_area_threshold = 0.40
    server.lan_raw_max_pixels = 20000
    server.lan_jpeg_area_threshold = 0.80
    server.lan_jpeg_min_pixels = 999999

    manager = _DummyEncoderManager({0: object(), 16: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 16},
        NetworkProfile.LAN,
        width=200,
        height=150,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
    )
    assert enc_type == 0


def test_select_encoder_for_update_lan_falls_back_to_zrle_without_raw():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_raw_area_threshold = 0.40
    server.lan_raw_max_pixels = 20000
    server.lan_jpeg_area_threshold = 0.80
    server.lan_jpeg_min_pixels = 999999

    manager = _DummyEncoderManager({16: object(), 2: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {16},
        NetworkProfile.LAN,
        width=200,
        height=150,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
    )
    assert enc_type == 16


def test_select_encoder_for_update_lan_low_bpp_prefers_raw():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_raw_area_threshold = 0.05
    server.lan_raw_max_pixels = 1000
    server.lan_jpeg_area_threshold = 0.25
    server.lan_jpeg_min_pixels = 32768

    manager = _DummyEncoderManager({0: object(), 16: object(), 2: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 16, 2},
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=1,
    )
    assert enc_type == 0


def test_select_encoder_for_update_lan_does_not_use_jpeg_for_16bpp():
    server = _server_without_init()
    server.enable_lan_adaptive_encoding = True
    server.lan_raw_area_threshold = 0.01
    server.lan_raw_max_pixels = 10
    server.lan_jpeg_area_threshold = 0.10
    server.lan_jpeg_min_pixels = 1024

    manager = _DummyEncoderManager({0: object(), 21: object(), 16: object()})
    enc_type, _ = server._select_encoder_for_update(
        manager,
        {0, 16, 21},
        NetworkProfile.LAN,
        width=1920,
        height=1080,
        fb_width=1920,
        fb_height=1080,
        content_type="lan",
        bytes_per_pixel=2,
    )
    assert enc_type == 0


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

    def get_best_encoder(self, _client_encodings, content_type="default"):
        if 0 in self.encoders:
            return 0, self.encoders[0]
        first_key = next(iter(self.encoders))
        return first_key, self.encoders[first_key]
