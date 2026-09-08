"""Adaptive streaming primitives used by PyVNCServer 3.6.

The controller deliberately uses only measurements available on the normal
blocking RFB send path.  A slow socket therefore naturally increases observed
frame time and creates backpressure without a separate network thread.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import blake2b
import threading
import time
from typing import Iterable


Rectangle = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class AdaptiveStreamConfig:
    enabled: bool = True
    min_fps: float = 12.0
    target_utilization: float = 0.80
    decrease_factor: float = 0.80
    increase_step_fps: float = 2.0
    overload_ratio: float = 1.10
    recovery_ratio: float = 0.72
    overload_samples: int = 2
    recovery_samples: int = 8
    ewma_alpha: float = 0.20
    merge_regions: bool = True
    merge_gap_px: int = 12
    merge_max_expansion: float = 1.35
    merge_force_count: int = 12
    cache_enabled: bool = True
    cache_max_entries: int = 512
    cache_max_bytes: int = 32 * 1024 * 1024
    cache_max_item_bytes: int = 1024 * 1024
    cache_ttl_seconds: float = 2.0
    reorder_encodings: bool = True
    adapt_tight_compression: bool = True


@dataclass(frozen=True, slots=True)
class AdaptiveStreamSnapshot:
    target_fps: float
    pressure: float
    network_pressure: float
    cpu_pressure: float
    frame_time_ewma: float
    send_time_ewma: float
    processing_time_ewma: float
    throughput_bps_ewma: float
    compression_ratio_ewma: float
    overloaded: bool


class AdaptiveStreamController:
    """Per-client adaptive pacing and region-coalescing controller."""

    def __init__(
        self,
        base_fps: float,
        config: AdaptiveStreamConfig | None = None,
    ) -> None:
        self.config = config or AdaptiveStreamConfig()
        self.base_fps = max(1.0, float(base_fps))
        self.min_fps = min(self.base_fps, max(1.0, float(self.config.min_fps)))
        self.target_fps = self.base_fps
        self.frame_time_ewma = 0.0
        self.send_time_ewma = 0.0
        self.processing_time_ewma = 0.0
        self.throughput_bps_ewma = 0.0
        self.compression_ratio_ewma = 1.0
        self._overload_streak = 0
        self._recovery_streak = 0
        self._sample_count = 0

    @property
    def target_interval(self) -> float:
        return 1.0 / max(1.0, self.target_fps)

    @property
    def pressure(self) -> float:
        budget = self.target_interval * max(0.10, self.config.target_utilization)
        if budget <= 0 or self.frame_time_ewma <= 0:
            return 0.0
        return self.frame_time_ewma / budget

    @property
    def network_pressure(self) -> float:
        budget = self.target_interval * max(0.10, self.config.target_utilization)
        if budget <= 0 or self.send_time_ewma <= 0:
            return 0.0
        return self.send_time_ewma / budget

    @property
    def cpu_pressure(self) -> float:
        budget = self.target_interval * max(0.10, self.config.target_utilization)
        if budget <= 0 or self.processing_time_ewma <= 0:
            return 0.0
        return self.processing_time_ewma / budget

    @property
    def overloaded(self) -> bool:
        return self.pressure >= self.config.overload_ratio

    def observe(
        self,
        frame_time: float,
        encoded_bytes: int,
        original_bytes: int,
        send_time: float = 0.0,
    ) -> AdaptiveStreamSnapshot:
        frame_time = max(0.0, float(frame_time))
        encoded_bytes = max(0, int(encoded_bytes))
        original_bytes = max(0, int(original_bytes))
        send_time = max(0.0, min(frame_time, float(send_time)))
        processing_time = max(0.0, frame_time - send_time)
        alpha = min(1.0, max(0.01, float(self.config.ewma_alpha)))

        self.frame_time_ewma = self._ewma(self.frame_time_ewma, frame_time, alpha)
        self.send_time_ewma = self._ewma(self.send_time_ewma, send_time, alpha)
        self.processing_time_ewma = self._ewma(
            self.processing_time_ewma, processing_time, alpha
        )
        if frame_time > 0:
            throughput = encoded_bytes / frame_time
            self.throughput_bps_ewma = self._ewma(
                self.throughput_bps_ewma, throughput, alpha
            )
        if original_bytes > 0:
            ratio = encoded_bytes / original_bytes
            self.compression_ratio_ewma = self._ewma(
                self.compression_ratio_ewma, ratio, alpha
            )

        self._sample_count += 1
        if self.config.enabled:
            self._retune_rate()
        return self.snapshot()

    def snapshot(self) -> AdaptiveStreamSnapshot:
        return AdaptiveStreamSnapshot(
            target_fps=self.target_fps,
            pressure=self.pressure,
            network_pressure=self.network_pressure,
            cpu_pressure=self.cpu_pressure,
            frame_time_ewma=self.frame_time_ewma,
            send_time_ewma=self.send_time_ewma,
            processing_time_ewma=self.processing_time_ewma,
            throughput_bps_ewma=self.throughput_bps_ewma,
            compression_ratio_ewma=self.compression_ratio_ewma,
            overloaded=self.overloaded,
        )

    def recommended_jpeg_quality(
        self,
        current_quality: int,
        minimum: int,
        maximum: int,
    ) -> int:
        minimum = max(1, int(minimum))
        maximum = max(minimum, min(100, int(maximum)))
        current = max(minimum, min(maximum, int(current_quality)))
        if not self.config.enabled or self._sample_count < 2:
            return current

        pressure = max(self.network_pressure, self.pressure * 0.65)
        if pressure >= 1.60:
            current -= 8
        elif pressure >= 1.25:
            current -= 4
        elif pressure >= 1.05:
            current -= 2
        elif pressure <= 0.55 and self.compression_ratio_ewma < 0.45:
            current += 2
        elif pressure <= 0.75 and self.compression_ratio_ewma < 0.35:
            current += 1
        return max(minimum, min(maximum, current))

    def recommended_tight_compression_level(
        self, current_level: int, minimum: int = 1, maximum: int = 9
    ) -> int:
        """Tune Tight CPU/bandwidth tradeoff; Tight can signal stream resets safely."""
        minimum = max(1, int(minimum))
        maximum = max(minimum, min(9, int(maximum)))
        current = max(minimum, min(maximum, int(current_level)))
        if not self.config.enabled or not self.config.adapt_tight_compression:
            return current
        if self.cpu_pressure >= 1.35 and self.cpu_pressure > self.network_pressure * 1.2:
            current -= 2
        elif self.cpu_pressure >= 1.05 and self.cpu_pressure > self.network_pressure:
            current -= 1
        elif self.network_pressure >= 1.20 and self.cpu_pressure <= 0.85:
            current += 1
        return max(minimum, min(maximum, current))

    def recommended_encoding_order(self, encodings: Iterable[int]) -> list[int]:
        """Reorder only already-negotiated encodings according to bottleneck type."""
        ordered = list(dict.fromkeys(int(enc) for enc in encodings))
        if not self.config.enabled or not self.config.reorder_encodings:
            return ordered
        if self._sample_count < 2:
            return ordered

        if self.network_pressure >= 1.05 and self.network_pressure >= self.cpu_pressure:
            preference = [21, 7, 16, 6, 5, 2, 0]
        elif self.cpu_pressure >= 1.05 and self.cpu_pressure > self.network_pressure:
            preference = [0, 5, 2, 21, 6, 16, 7]
        else:
            return ordered

        rank = {enc: index for index, enc in enumerate(preference)}
        indexed = list(enumerate(ordered))
        indexed.sort(key=lambda item: (rank.get(item[1], len(preference)), item[0]))
        return [enc for _, enc in indexed]

    def merge_changed_regions(
        self,
        regions: Iterable[Rectangle],
        framebuffer_width: int,
        framebuffer_height: int,
    ) -> list[Rectangle]:
        normalized = [
            clipped
            for clipped in (
                _clip_rect(rect, framebuffer_width, framebuffer_height)
                for rect in regions
            )
            if clipped is not None
        ]
        if (
            not self.config.enabled
            or not self.config.merge_regions
            or len(normalized) < 2
        ):
            return normalized

        # Under pressure we tolerate a larger merged bounding box to reduce
        # encoder scheduling and per-rectangle protocol overhead.
        pressure = max(0.0, self.pressure)
        expansion_limit = float(self.config.merge_max_expansion)
        if pressure >= 1.5:
            expansion_limit *= 1.35
        elif pressure >= 1.1:
            expansion_limit *= 1.15
        expansion_limit = max(1.0, expansion_limit)
        gap = max(0, int(self.config.merge_gap_px))
        if pressure >= 1.25:
            gap = max(gap, int(gap * 1.75))

        regions_out = list(normalized)
        changed = True
        while changed and len(regions_out) > 1:
            changed = False
            best_pair: tuple[int, int, Rectangle] | None = None
            best_cost = float("inf")
            force = len(regions_out) >= max(2, int(self.config.merge_force_count))
            for i in range(len(regions_out)):
                for j in range(i + 1, len(regions_out)):
                    a = regions_out[i]
                    b = regions_out[j]
                    nearby = _near_or_overlapping(a, b, gap)
                    if not nearby and not force:
                        continue
                    union = _union_rect(a, b)
                    area_sum = _rect_area(a) + _rect_area(b)
                    expansion = _rect_area(union) / max(1, area_sum)
                    allowed_expansion = expansion_limit * (1.75 if force else 1.0)
                    if expansion > allowed_expansion:
                        continue
                    # Prefer the cheapest expansion; when forced, this also
                    # picks the least harmful pair to reduce rectangle count.
                    if expansion < best_cost:
                        best_cost = expansion
                        best_pair = (i, j, union)
            if best_pair is not None:
                i, j, union = best_pair
                regions_out[i] = union
                del regions_out[j]
                changed = True

        return regions_out

    def _retune_rate(self) -> None:
        pressure = self.pressure
        if pressure >= self.config.overload_ratio:
            self._overload_streak += 1
            self._recovery_streak = 0
            if self._overload_streak >= max(1, self.config.overload_samples):
                reduced = self.target_fps * max(0.20, min(0.95, self.config.decrease_factor))
                self.target_fps = max(self.min_fps, reduced)
                self._overload_streak = 0
            return

        if pressure <= self.config.recovery_ratio:
            self._recovery_streak += 1
            self._overload_streak = 0
            if self._recovery_streak >= max(1, self.config.recovery_samples):
                self.target_fps = min(
                    self.base_fps,
                    self.target_fps + max(0.1, self.config.increase_step_fps),
                )
                self._recovery_streak = 0
            return

        self._overload_streak = 0
        self._recovery_streak = 0

    @staticmethod
    def _ewma(previous: float, value: float, alpha: float) -> float:
        if previous <= 0:
            return value
        return previous * (1.0 - alpha) + value * alpha


@dataclass(frozen=True, slots=True)
class EncodedRegionCacheKey:
    encoding_type: int
    width: int
    height: int
    bytes_per_pixel: int
    pixel_format_key: tuple[int, ...]
    encoder_variant: int
    digest: bytes


@dataclass(slots=True)
class _CacheEntry:
    payload: bytes
    created_at: float
    last_access: float


class EncodedRegionCache:
    """Small shared TTL/LRU cache for stateless rectangle encodings.

    Stateful wire formats (CopyRect, Zlib, Tight, ZRLE, H.264) must never use
    this cache because their payload can depend on per-client stream history.
    """

    CACHEABLE_ENCODINGS = frozenset({0, 2, 5, 21})

    def __init__(
        self,
        max_entries: int = 512,
        max_bytes: int = 32 * 1024 * 1024,
        max_item_bytes: int = 1024 * 1024,
        ttl_seconds: float = 2.0,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1024, int(max_bytes))
        self.max_item_bytes = max(1, int(max_item_bytes))
        self.ttl_seconds = max(0.05, float(ttl_seconds))
        self._entries: OrderedDict[EncodedRegionCacheKey, _CacheEntry] = OrderedDict()
        self._total_bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._lock = threading.Lock()

    @property
    def stats(self) -> dict[str, int | float]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "bytes": self._total_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": self._hits / total if total else 0.0,
            }

    def make_key(
        self,
        encoding_type: int,
        pixel_data: bytes,
        width: int,
        height: int,
        bytes_per_pixel: int,
        pixel_format: dict | None,
        encoder_variant: int = 0,
    ) -> EncodedRegionCacheKey | None:
        if int(encoding_type) not in self.CACHEABLE_ENCODINGS:
            return None
        if len(pixel_data) > self.max_item_bytes * 8:
            # Avoid spending more CPU hashing huge full-screen buffers than the
            # cache is likely to save. Small/medium dirty regions are the target.
            return None
        digest = blake2b(pixel_data, digest_size=16).digest()
        return EncodedRegionCacheKey(
            encoding_type=int(encoding_type),
            width=int(width),
            height=int(height),
            bytes_per_pixel=int(bytes_per_pixel),
            pixel_format_key=_pixel_format_key(pixel_format),
            encoder_variant=int(encoder_variant),
            digest=digest,
        )

    def get(self, key: EncodedRegionCacheKey | None) -> bytes | None:
        if key is None:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if now - entry.created_at > self.ttl_seconds:
                self._remove_locked(key)
                self._misses += 1
                return None
            entry.last_access = now
            self._entries.move_to_end(key)
            self._hits += 1
            return entry.payload

    def put(self, key: EncodedRegionCacheKey | None, payload: bytes) -> None:
        if key is None:
            return
        payload = bytes(payload)
        if len(payload) > self.max_item_bytes:
            return
        now = time.monotonic()
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._total_bytes -= len(old.payload)
            self._entries[key] = _CacheEntry(payload, now, now)
            self._total_bytes += len(payload)
            self._prune_locked(now)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0

    def _prune_locked(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry.created_at > self.ttl_seconds
        ]
        for key in expired:
            self._remove_locked(key)
        while (
            len(self._entries) > self.max_entries
            or self._total_bytes > self.max_bytes
        ):
            _, entry = self._entries.popitem(last=False)
            self._total_bytes -= len(entry.payload)
            self._evictions += 1

    def _remove_locked(self, key: EncodedRegionCacheKey) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes -= len(entry.payload)
            self._evictions += 1


def _pixel_format_key(pixel_format: dict | None) -> tuple[int, ...]:
    if not pixel_format:
        return ()
    fields = (
        "bits_per_pixel", "depth", "big_endian", "true_color",
        "red_max", "green_max", "blue_max",
        "red_shift", "green_shift", "blue_shift",
    )
    return tuple(int(pixel_format.get(field, 0) or 0) for field in fields)


def _rect_area(rect: Rectangle) -> int:
    return max(0, int(rect[2])) * max(0, int(rect[3]))


def _union_rect(a: Rectangle, b: Rectangle) -> Rectangle:
    x1 = min(a[0], b[0])
    y1 = min(a[1], b[1])
    x2 = max(a[0] + a[2], b[0] + b[2])
    y2 = max(a[1] + a[3], b[1] + b[3])
    return x1, y1, x2 - x1, y2 - y1


def _near_or_overlapping(a: Rectangle, b: Rectangle, gap: int) -> bool:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    return not (
        ax2 + gap < bx1
        or bx2 + gap < ax1
        or ay2 + gap < by1
        or by2 + gap < ay1
    )


def _clip_rect(rect: Rectangle, width: int, height: int) -> Rectangle | None:
    x, y, w, h = map(int, rect)
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(int(width), x + w)
    y2 = min(int(height), y + h)
    if x1 >= x2 or y1 >= y2:
        return None
    return x1, y1, x2 - x1, y2 - y1
