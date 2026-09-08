#!/usr/bin/env python3
"""PyVNCServer 4.1 latency hot-path microbenchmark.

This benchmark intentionally avoids network/capture-driver variability. It
measures CPU-side operations that sit between a captured frame and socket send:
exact unchanged-frame detection, dirty-rectangle compaction and framebuffer
region extraction.

For end-to-end LAN request/response latency use benchmark_lan_latency.py on the
actual Windows host.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Callable

from pyvncserver._core.change_detector import AdaptiveChangeDetector
from pyvncserver.app.server import VNCServerV3
from pyvncserver.runtime.adaptive import AdaptiveStreamConfig, AdaptiveStreamController


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * q)))
    return ordered[index]


def timed_ms(fn: Callable[[], object], iterations: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(max(1, iterations)):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1_000_000.0)
    return {
        "min_ms": min(samples),
        "avg_ms": statistics.mean(samples),
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
        "max_ms": max(samples),
    }


def run(width: int, height: int, iterations: int) -> dict[str, object]:
    bytes_per_pixel = 4
    # Distinct but identical immutable byte strings exercise the exact memcmp
    # fast-path without benefiting from Python object identity.
    frame_a = bytes(bytearray(width * height * bytes_per_pixel))
    frame_b = bytes(bytearray(frame_a))

    detector = AdaptiveChangeDetector(width, height)
    detector.detect_changes(frame_a, bytes_per_pixel)
    unchanged = timed_ms(
        lambda: detector.detect_changes(frame_b, bytes_per_pixel),
        iterations,
    )

    controller = AdaptiveStreamController(
        120,
        AdaptiveStreamConfig(
            merge_regions=True,
            merge_gap_px=12,
            merge_max_expansion=1.35,
            merge_force_count=12,
        ),
    )

    def make_regions(count: int) -> list[tuple[int, int, int, int]]:
        cols = max(1, width // 96)
        return [
            (
                8 + (i % cols) * 80,
                8 + (i // cols) * 64,
                48,
                40,
            )
            for i in range(count)
        ]

    merges: dict[str, dict[str, float]] = {}
    for count in (8, 16, 32, 64):
        regions = make_regions(count)
        merges[str(count)] = timed_ms(
            lambda regions=regions: controller.merge_changed_regions(regions, width, height),
            iterations,
        )

    server = object.__new__(VNCServerV3)
    full_width_height = min(height, 500)
    inner_width = min(800, max(1, width - 32))
    inner_height = min(500, max(1, height - 32))
    extract_full_width = timed_ms(
        lambda: server._extract_region(
            frame_a, width, height, 0, 0, width, full_width_height, bytes_per_pixel
        ),
        iterations,
    )
    extract_inner = timed_ms(
        lambda: server._extract_region(
            frame_a, width, height, 16, 16, inner_width, inner_height, bytes_per_pixel
        ),
        iterations,
    )

    return {
        "framebuffer": {
            "width": width,
            "height": height,
            "bytes_per_pixel": bytes_per_pixel,
            "bytes": len(frame_a),
        },
        "iterations": iterations,
        "unchanged_frame_detection": unchanged,
        "merge_regions": merges,
        "extract_full_width": extract_full_width,
        "extract_inner": extract_inner,
    }


def print_human(result: dict[str, object]) -> None:
    fb = result["framebuffer"]
    assert isinstance(fb, dict)
    print("PyVNCServer 4.1 latency hot-path benchmark")
    print(f"Framebuffer: {fb['width']}x{fb['height']}x{fb['bytes_per_pixel']} ({fb['bytes'] / 1024 / 1024:.2f} MiB)")
    print(f"Iterations:  {result['iterations']}")

    def line(name: str, stats: dict[str, float]) -> None:
        print(
            f"{name:<26} avg={stats['avg_ms']:8.3f} ms  "
            f"p50={stats['p50_ms']:8.3f}  p95={stats['p95_ms']:8.3f}  "
            f"p99={stats['p99_ms']:8.3f}  max={stats['max_ms']:8.3f}"
        )

    print("\nCPU hot path")
    line("unchanged frame", result["unchanged_frame_detection"])  # type: ignore[arg-type]
    line("extract full-width", result["extract_full_width"])  # type: ignore[arg-type]
    line("extract inner", result["extract_inner"])  # type: ignore[arg-type]
    print("\nDirty-region compaction")
    merges = result["merge_regions"]
    assert isinstance(merges, dict)
    for count in ("8", "16", "32", "64"):
        line(f"merge {count} rects", merges[count])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    result = run(max(64, args.width), max(64, args.height), max(1, args.iterations))
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_human(result)
