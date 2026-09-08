"""Server-wide screen capture producer with generation-aware dirty-region history."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import logging
import threading
import time

from pyvncserver._core.capture_backends import CaptureFrame, CaptureMetadata, CaptureMoveRect
from pyvncserver._core.change_detector import AdaptiveChangeDetector
from pyvncserver._core.screen_capture import CaptureResult, ScreenCapture


NATIVE_BGR0 = {
    "bits_per_pixel": 32,
    "depth": 24,
    "big_endian_flag": 0,
    "true_colour_flag": 1,
    "red_max": 255,
    "green_max": 255,
    "blue_max": 255,
    "red_shift": 16,
    "green_shift": 8,
    "blue_shift": 0,
}


@dataclass(frozen=True, slots=True)
class FrameSnapshot:
    generation: int
    frame: CaptureFrame
    published_at: float = 0.0


@dataclass(frozen=True, slots=True)
class _HistoryEntry:
    generation: int
    width: int
    height: int
    dirty_regions: tuple[tuple[int, int, int, int], ...]
    move_rects: tuple[CaptureMoveRect, ...]
    backend_name: str
    supports_move_rects: bool


class CaptureProducer:
    """Capture the desktop once and fan out snapshots to all client sessions.

    Dirty regions are calculated once per captured native frame and retained in
    a bounded generation history. A slow client therefore receives the union
    of every change since the generation it last consumed, rather than only the
    most recent frame-to-frame delta.
    """

    def __init__(self, capture: ScreenCapture, fps: float = 90.0,
                 history_size: int = 256, conversion_cache_entries: int = 4,
                 conversion_cache_max_bytes: int = 64 * 1024 * 1024) -> None:
        self.capture = capture
        self.fps = max(1.0, float(fps))
        self.logger = logging.getLogger(__name__)
        self._interval = 1.0 / self.fps
        self._lock = threading.Condition()
        self._running = False
        self._thread: threading.Thread | None = None
        self._snapshot: FrameSnapshot | None = None
        self._generation = 0
        self._history: deque[_HistoryEntry] = deque(maxlen=max(8, int(history_size)))
        self._change_detector: AdaptiveChangeDetector | None = None
        self._detector_size: tuple[int, int] | None = None
        self._conversion_lock = threading.Lock()
        self._conversion_cache: OrderedDict[tuple[int, tuple[int, ...]], CaptureResult] = OrderedDict()
        self._conversion_cache_bytes = 0
        self._conversion_cache_entries = max(1, int(conversion_cache_entries))
        self._conversion_cache_max_bytes = max(1024, int(conversion_cache_max_bytes))
        self._conversion_cache_hits = 0
        self._conversion_cache_misses = 0
        self.capture.set_cache_frame_rate(self.fps)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="CaptureProducer",
            daemon=False,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._running = False
        with self._lock:
            self._lock.notify_all()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        next_tick = time.perf_counter()
        try:
            while self._running:
                frame = self.capture.capture_frame(NATIVE_BGR0)
                if frame.result.pixel_data is not None:
                    with self._lock:
                        self._generation += 1
                        frame = self._with_shared_dirty_metadata(frame)
                        self._snapshot = FrameSnapshot(
                            self._generation, frame, time.perf_counter()
                        )
                        self._append_history(self._generation, frame)
                        self._lock.notify_all()

                next_tick += self._interval
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    # Do not accumulate lag when capture is slower than target.
                    next_tick = time.perf_counter()
        finally:
            self.capture.close_current_thread_sessions()

    def _with_shared_dirty_metadata(self, frame: CaptureFrame) -> CaptureFrame:
        result = frame.result
        if result.pixel_data is None or result.width <= 0 or result.height <= 0:
            return frame

        metadata = frame.metadata
        dirty_regions = metadata.dirty_regions
        if dirty_regions is None:
            size = (result.width, result.height)
            if self._change_detector is None or self._detector_size != size:
                self._change_detector = AdaptiveChangeDetector(*size)
                self._detector_size = size
                # The first frame for a new size must be considered fully dirty.
                self._change_detector.detect_changes(result.pixel_data, 4)
                dirty_regions = [(0, 0, result.width, result.height)]
            else:
                detected = self._change_detector.detect_changes(result.pixel_data, 4)
                dirty_regions = (
                    [(0, 0, result.width, result.height)]
                    if detected is None
                    else [tuple(region) for region in detected]
                )

        merged_metadata = CaptureMetadata(
            backend_name=f"{metadata.backend_name}+producer-diff",
            dirty_regions=list(dirty_regions),
            move_rects=list(metadata.move_rects),
            supports_dirty_regions=True,
            supports_move_rects=metadata.supports_move_rects,
        )
        return CaptureFrame(result=result, metadata=merged_metadata)

    def _append_history(self, generation: int, frame: CaptureFrame) -> None:
        result = frame.result
        metadata = frame.metadata
        dirty = tuple(tuple(map(int, region)) for region in (metadata.dirty_regions or ()))
        self._history.append(_HistoryEntry(
            generation=generation,
            width=result.width,
            height=result.height,
            dirty_regions=dirty,
            move_rects=tuple(metadata.move_rects),
            backend_name=metadata.backend_name,
            supports_move_rects=metadata.supports_move_rects,
        ))

    def get_frame(self, pixel_format: dict, timeout: float = 5.0,
                  since_generation: int | None = None) -> FrameSnapshot:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._lock:
            while self._snapshot is None and self._running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._lock.wait(timeout=remaining)
            snapshot = self._snapshot
            if snapshot is not None:
                metadata = self._metadata_since(snapshot, since_generation)
                snapshot = FrameSnapshot(
                    snapshot.generation,
                    CaptureFrame(result=snapshot.frame.result, metadata=metadata),
                    snapshot.published_at,
                )

        if snapshot is None:
            # Unit-level/direct handle_client use before start(). Each capture is
            # assigned a unique generation so incremental logic cannot mistake a
            # newly captured frame for an already-consumed one.
            frame = self.capture.capture_frame(NATIVE_BGR0)
            generation = time.monotonic_ns()
            if frame.result.pixel_data is not None:
                frame = self._with_shared_dirty_metadata(frame)
                if since_generation is not None and since_generation < 0:
                    frame = CaptureFrame(
                        result=frame.result,
                        metadata=CaptureMetadata(
                            backend_name=frame.metadata.backend_name,
                            dirty_regions=[(0, 0, frame.result.width, frame.result.height)],
                            move_rects=[],
                            supports_dirty_regions=True,
                            supports_move_rects=False,
                        ),
                    )
            snapshot = FrameSnapshot(generation, frame, time.perf_counter())

        native_result = snapshot.frame.result
        if native_result.pixel_data is None or _is_native_bgr0(pixel_format):
            return snapshot

        cache_key = (snapshot.generation, _pixel_format_cache_key(pixel_format))
        with self._conversion_lock:
            cached = self._conversion_cache.get(cache_key)
            if cached is not None:
                self._conversion_cache_hits += 1
                self._conversion_cache.move_to_end(cache_key)
                result = cached
            else:
                self._conversion_cache_misses += 1
                started = time.perf_counter()
                converted = self.capture.convert_native_bgr0(
                    native_result.pixel_data,
                    native_result.width,
                    native_result.height,
                    pixel_format,
                )
                result = CaptureResult(
                    converted,
                    None,
                    native_result.width,
                    native_result.height,
                    native_result.capture_time + (time.perf_counter() - started),
                )
                self._conversion_cache[cache_key] = result
                self._conversion_cache_bytes += len(converted)
                self._prune_conversion_cache_locked(snapshot.generation)

        return FrameSnapshot(
            snapshot.generation,
            CaptureFrame(result=result, metadata=snapshot.frame.metadata),
            snapshot.published_at,
        )

    @property
    def latest_generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def stats(self) -> dict[str, int | float]:
        with self._conversion_lock:
            total = self._conversion_cache_hits + self._conversion_cache_misses
            return {
                "fps": self.fps,
                "generation": self._generation,
                "conversion_cache_entries": len(self._conversion_cache),
                "conversion_cache_bytes": self._conversion_cache_bytes,
                "conversion_cache_hits": self._conversion_cache_hits,
                "conversion_cache_misses": self._conversion_cache_misses,
                "conversion_cache_hit_rate": (
                    self._conversion_cache_hits / total if total else 0.0
                ),
            }

    def _prune_conversion_cache_locked(self, current_generation: int) -> None:
        # Converted full frames are only useful for the currently published
        # generation. Remove old generations first, then enforce memory caps.
        stale = [key for key in self._conversion_cache if key[0] != current_generation]
        for key in stale:
            result = self._conversion_cache.pop(key)
            if result.pixel_data is not None:
                self._conversion_cache_bytes -= len(result.pixel_data)
        while (
            len(self._conversion_cache) > self._conversion_cache_entries
            or self._conversion_cache_bytes > self._conversion_cache_max_bytes
        ):
            _, result = self._conversion_cache.popitem(last=False)
            if result.pixel_data is not None:
                self._conversion_cache_bytes -= len(result.pixel_data)

    def _metadata_since(self, snapshot: FrameSnapshot,
                        since_generation: int | None) -> CaptureMetadata:
        result = snapshot.frame.result
        current = snapshot.generation
        if result.pixel_data is None:
            return snapshot.frame.metadata

        if since_generation is None:
            return snapshot.frame.metadata
        if since_generation < 0:
            return CaptureMetadata(
                backend_name=snapshot.frame.metadata.backend_name,
                dirty_regions=[(0, 0, result.width, result.height)],
                move_rects=[],
                supports_dirty_regions=True,
                supports_move_rects=False,
            )
        if since_generation >= current:
            return CaptureMetadata(
                backend_name=snapshot.frame.metadata.backend_name,
                dirty_regions=[],
                move_rects=[],
                supports_dirty_regions=True,
                supports_move_rects=False,
            )

        entries = [entry for entry in self._history if entry.generation > since_generation]
        expected = current - since_generation
        if not entries or len(entries) < expected or entries[-1].generation != current:
            return self._full_metadata(snapshot)
        if any((entry.width, entry.height) != (result.width, result.height) for entry in entries):
            return self._full_metadata(snapshot)

        dirty: list[tuple[int, int, int, int]] = []
        for entry in entries:
            dirty.extend(entry.dirty_regions)
        dirty = _coalesce_dirty_regions(dirty, result.width, result.height)

        # CopyRect is only safe when the client is exactly one producer frame
        # behind. If it skipped frames, send pixels for the union of dirty areas.
        latest = entries[-1]
        moves = list(latest.move_rects) if len(entries) == 1 else []
        return CaptureMetadata(
            backend_name=latest.backend_name,
            dirty_regions=dirty,
            move_rects=moves,
            supports_dirty_regions=True,
            supports_move_rects=bool(moves and latest.supports_move_rects),
        )

    def _full_metadata(self, snapshot: FrameSnapshot) -> CaptureMetadata:
        result = snapshot.frame.result
        return CaptureMetadata(
            backend_name=snapshot.frame.metadata.backend_name,
            dirty_regions=[(0, 0, result.width, result.height)],
            move_rects=[],
            supports_dirty_regions=True,
            supports_move_rects=False,
        )


def _coalesce_dirty_regions(regions: list[tuple[int, int, int, int]],
                            width: int, height: int) -> list[tuple[int, int, int, int]]:
    if not regions:
        return []
    # Deduplicate exact rectangles first.
    unique = list(dict.fromkeys(region for region in regions if region[2] > 0 and region[3] > 0))
    total_area = sum(w * h for _, _, w, h in unique)
    screen_area = max(1, width * height)
    if len(unique) > 64 or total_area >= screen_area * 0.60:
        return [(0, 0, width, height)]
    if len(unique) <= 16:
        return unique

    left = min(x for x, _, _, _ in unique)
    top = min(y for _, y, _, _ in unique)
    right = max(x + w for x, _, w, _ in unique)
    bottom = max(y + h for _, y, _, h in unique)
    return [(left, top, min(width, right) - max(0, left), min(height, bottom) - max(0, top))]


def _pixel_format_cache_key(pixel_format: dict) -> tuple[int, ...]:
    fields = (
        "bits_per_pixel", "depth", "big_endian_flag", "true_colour_flag",
        "red_max", "green_max", "blue_max", "red_shift", "green_shift", "blue_shift",
    )
    return tuple(int(pixel_format.get(field, 0) or 0) for field in fields)


def _is_native_bgr0(pixel_format: dict) -> bool:
    return (
        pixel_format.get("bits_per_pixel") == 32
        and pixel_format.get("depth") == 24
        and not pixel_format.get("big_endian_flag")
        and bool(pixel_format.get("true_colour_flag"))
        and pixel_format.get("red_max") == 255
        and pixel_format.get("green_max") == 255
        and pixel_format.get("blue_max") == 255
        and pixel_format.get("red_shift") == 16
        and pixel_format.get("green_shift") == 8
        and pixel_format.get("blue_shift") == 0
    )
