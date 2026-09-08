from __future__ import annotations

import logging

from pyvncserver.runtime.adaptive import EncodedRegionCache
from pyvncserver.session.runtime import SessionRuntimeMixin
from pyvncserver._core.encodings import EncoderManager
from pyvncserver._core.parallel_encoder import ParallelEncoder
from pyvncserver._core.server_utils import NetworkProfile


class _Runtime(SessionRuntimeMixin):
    logger = logging.getLogger("test.adaptive.runtime")
    tight_stream_reset_for_ultravnc = False
    lan_jpeg_quality_min = 60
    lan_jpeg_quality_max = 95

    def __init__(self, cache):
        self.encoded_region_cache = cache


def test_runtime_reuses_hextile_payload_from_shared_cache():
    cache = EncodedRegionCache(max_item_bytes=4096)
    runtime = _Runtime(cache)
    manager = EncoderManager(enable_tight=False, enable_jpeg=False)
    encoder = manager.encoders[5]
    original_encode = encoder.encode
    calls = {"count": 0}

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original_encode(*args, **kwargs)

    encoder.encode = counted
    pixels = bytes([10, 20, 30, 0]) * 16
    kwargs = dict(
        encoder_manager=manager,
        client_encodings=[5],
        network_profile=NetworkProfile.LAN,
        x=0,
        y=0,
        width=4,
        height=4,
        fb_width=4,
        fb_height=4,
        content_type="lan",
        pixel_data=pixels,
        full_frame=pixels,
        request_region=(0, 0, 4, 4),
        allow_copyrect=False,
        bytes_per_pixel=4,
        pixel_format={"bits_per_pixel": 32},
    )

    first = runtime._encode_rectangle_for_update(**kwargs)
    second = runtime._encode_rectangle_for_update(**kwargs)
    assert first[0] == second[0] == 5
    assert first[2] == second[2]
    assert calls["count"] == 1
    assert cache.stats["hits"] == 1


def test_parallel_encoder_cache_is_shared_between_client_views():
    cache = EncodedRegionCache(max_item_bytes=4096)

    class FakeEncoder:
        def __init__(self):
            self.calls = 0

        def encode(self, pixels, width, height, bpp):
            self.calls += 1
            return b"cached-hextile"

    encoder = FakeEncoder()
    region = ((0, 0, 4, 4), b"x" * 64, 5, encoder)
    first = ParallelEncoder(max_workers=1, encoded_region_cache=cache)
    second = ParallelEncoder(max_workers=1, encoded_region_cache=cache)
    try:
        assert first.encode_regions([region], 4)[0].encoded_data == b"cached-hextile"
        assert second.encode_regions([region], 4)[0].encoded_data == b"cached-hextile"
        assert encoder.calls == 1
        assert cache.stats["hits"] == 1
    finally:
        first.shutdown()
        second.shutdown()
