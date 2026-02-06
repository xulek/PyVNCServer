"""
Targeted unit tests for VNCServerV3 helper logic.
"""

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
