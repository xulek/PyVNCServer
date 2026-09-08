from __future__ import annotations

import time

from pyvncserver.runtime.adaptive import (
    AdaptiveStreamConfig,
    AdaptiveStreamController,
    EncodedRegionCache,
)
from vnc_lib.server_utils import PerformanceThrottler


def test_controller_reduces_fps_under_sustained_pressure():
    config = AdaptiveStreamConfig(
        min_fps=10,
        overload_samples=2,
        recovery_samples=3,
        ewma_alpha=1.0,
    )
    controller = AdaptiveStreamController(60, config)

    controller.observe(0.030, 1000, 4000)
    assert controller.target_fps == 60
    controller.observe(0.030, 1000, 4000)
    assert controller.target_fps == 48

    for _ in range(20):
        controller.observe(0.100, 1000, 4000)
    assert controller.target_fps >= 10
    assert controller.target_fps < 48


def test_controller_recovers_gradually_when_frame_budget_is_healthy():
    config = AdaptiveStreamConfig(
        min_fps=10,
        overload_samples=1,
        recovery_samples=2,
        increase_step_fps=5,
        ewma_alpha=1.0,
    )
    controller = AdaptiveStreamController(60, config)
    controller.observe(0.040, 1000, 4000)
    reduced = controller.target_fps
    assert reduced < 60

    controller.observe(0.001, 500, 4000)
    controller.observe(0.001, 500, 4000)
    assert controller.target_fps > reduced
    assert controller.target_fps <= 60


def test_jpeg_quality_reacts_to_pressure():
    config = AdaptiveStreamConfig(overload_samples=99, ewma_alpha=1.0)
    controller = AdaptiveStreamController(30, config)
    controller.observe(0.060, 100_000, 400_000)
    controller.observe(0.060, 100_000, 400_000)
    assert controller.recommended_jpeg_quality(84, 60, 95) < 84

    controller.observe(0.005, 20_000, 400_000)
    assert controller.recommended_jpeg_quality(80, 60, 95) >= 80


def test_region_merging_combines_nearby_regions_without_large_expansion():
    controller = AdaptiveStreamController(
        30,
        AdaptiveStreamConfig(merge_gap_px=8, merge_max_expansion=1.5),
    )
    merged = controller.merge_changed_regions(
        [(0, 0, 20, 20), (22, 0, 20, 20), (200, 200, 10, 10)],
        300,
        300,
    )
    assert (0, 0, 42, 20) in merged
    assert (200, 200, 10, 10) in merged
    assert len(merged) == 2


def test_region_merging_clips_invalid_regions():
    controller = AdaptiveStreamController(30)
    assert controller.merge_changed_regions(
        [(-5, -5, 10, 10), (200, 200, 20, 20)], 100, 100
    ) == [(0, 0, 5, 5)]


def test_encoded_region_cache_hits_for_same_stateless_payload():
    cache = EncodedRegionCache(max_entries=4, max_bytes=1024, max_item_bytes=256)
    pixels = b"abcd" * 8
    key = cache.make_key(5, pixels, 4, 2, 4, {"bits_per_pixel": 32})
    assert key is not None
    assert cache.get(key) is None
    cache.put(key, b"encoded")
    assert cache.get(key) == b"encoded"
    assert cache.stats["hits"] == 1


def test_cache_rejects_stateful_encoding():
    cache = EncodedRegionCache()
    assert cache.make_key(7, b"pixels", 1, 1, 4, None) is None  # Tight
    assert cache.make_key(6, b"pixels", 1, 1, 4, None) is None  # Zlib
    assert cache.make_key(16, b"pixels", 1, 1, 4, None) is None  # ZRLE


def test_cache_key_separates_jpeg_quality_variants():
    cache = EncodedRegionCache()
    pixels = b"x" * 32
    low = cache.make_key(21, pixels, 4, 2, 4, None, encoder_variant=60)
    high = cache.make_key(21, pixels, 4, 2, 4, None, encoder_variant=90)
    assert low != high


def test_cache_ttl_expires_entries():
    cache = EncodedRegionCache(ttl_seconds=0.05)
    key = cache.make_key(0, b"1234", 1, 1, 4, None)
    cache.put(key, b"1234")
    assert cache.get(key) == b"1234"
    time.sleep(0.06)
    assert cache.get(key) is None


def test_performance_throttler_rate_can_be_updated():
    throttler = PerformanceThrottler(60)
    assert throttler.max_rate == 60
    throttler.set_max_rate(20)
    assert throttler.max_rate == 20
    assert abs(throttler.min_interval - 0.05) < 1e-9


def test_forced_region_reduction_does_not_merge_widely_separated_damage():
    controller = AdaptiveStreamController(
        30,
        AdaptiveStreamConfig(merge_force_count=4, merge_gap_px=0, merge_max_expansion=1.2),
    )
    regions = [(0, 0, 5, 5), (100, 0, 5, 5), (0, 100, 5, 5), (100, 100, 5, 5)]
    assert controller.merge_changed_regions(regions, 200, 200) == regions


def test_controller_separates_network_and_cpu_pressure():
    controller = AdaptiveStreamController(30, AdaptiveStreamConfig(ewma_alpha=1.0))
    snapshot = controller.observe(0.040, 1000, 4000, send_time=0.030)
    assert snapshot.network_pressure > snapshot.cpu_pressure


def test_network_pressure_prefers_compressed_encodings():
    config = AdaptiveStreamConfig(ewma_alpha=1.0, overload_samples=99)
    controller = AdaptiveStreamController(30, config)
    controller.observe(0.040, 1000, 4000, send_time=0.035)
    controller.observe(0.040, 1000, 4000, send_time=0.035)
    ordered = controller.recommended_encoding_order([0, 5, 7, 16, 6, 21])
    assert ordered[0] == 21
    assert ordered.index(7) < ordered.index(0)


def test_cpu_pressure_prefers_lightweight_encodings_and_reduces_tight_level():
    config = AdaptiveStreamConfig(ewma_alpha=1.0, overload_samples=99)
    controller = AdaptiveStreamController(30, config)
    controller.observe(0.040, 1000, 4000, send_time=0.002)
    controller.observe(0.040, 1000, 4000, send_time=0.002)
    ordered = controller.recommended_encoding_order([7, 16, 6, 5, 0])
    assert ordered[0] == 0
    assert controller.recommended_tight_compression_level(5) < 5
