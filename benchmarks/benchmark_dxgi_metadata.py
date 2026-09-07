"""Inspect DXGI dirty/move metadata quality on a real Windows desktop.

Run on Windows with the performance extra installed:

    python -m pip install -e ".[performance]"
    python benchmarks/benchmark_dxgi_metadata.py --frames 300 --fps 60

The benchmark is diagnostic rather than a synthetic score. It reports how
often native Desktop Duplication metadata was available, rectangle counts and
the approximate fraction of the framebuffer affected by each frame.
"""

from __future__ import annotations

import argparse
import statistics
import time

from vnc_lib.screen_capture import ScreenCapture


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark DXGI dirty/move metadata")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--fps", type=float, default=60.0)
    args = parser.parse_args()

    frames = max(1, args.frames)
    fps = max(1.0, args.fps)
    interval = 1.0 / fps
    capture = ScreenCapture(backend_preference="dxcam")
    if capture.get_backend_name() != "dxcam":
        raise SystemExit(
            "DXCam backend is unavailable; install the performance extra on Windows"
        )

    capture.set_cache_frame_rate(fps)
    native_frames = 0
    fallback_frames = 0
    dirty_counts: list[int] = []
    move_counts: list[int] = []
    changed_ratios: list[float] = []
    capture_ms: list[float] = []

    next_tick = time.perf_counter()
    try:
        for _ in range(frames):
            frame = capture.capture_frame(NATIVE_BGR0)
            result = frame.result
            metadata = frame.metadata
            if result.pixel_data is None:
                continue

            capture_ms.append(result.capture_time * 1000.0)
            if metadata.dirty_regions is None:
                fallback_frames += 1
            else:
                native_frames += 1
                dirty_counts.append(len(metadata.dirty_regions))
                move_counts.append(len(metadata.move_rects))
                changed_area = sum(w * h for _, _, w, h in metadata.dirty_regions)
                changed_ratios.append(
                    min(1.0, changed_area / max(1, result.width * result.height))
                )

            next_tick += interval
            delay = next_tick - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.perf_counter()
    finally:
        capture.close_current_thread_sessions()

    total = native_frames + fallback_frames
    print(f"backend:             {capture.get_backend_name()}")
    print(f"frames sampled:      {total}")
    print(f"native metadata:     {native_frames} ({native_frames / max(1, total):.1%})")
    print(f"metadata fallbacks:  {fallback_frames}")
    if capture_ms:
        ordered = sorted(capture_ms)
        p95 = ordered[int((len(ordered) - 1) * 0.95)]
        print(f"capture avg:         {statistics.mean(capture_ms):.2f} ms")
        print(f"capture p95:         {p95:.2f} ms")
    if dirty_counts:
        print(f"dirty rects avg:     {statistics.mean(dirty_counts):.2f}")
        print(f"move rects avg:      {statistics.mean(move_counts):.2f}")
        print(f"changed area avg:    {statistics.mean(changed_ratios):.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
