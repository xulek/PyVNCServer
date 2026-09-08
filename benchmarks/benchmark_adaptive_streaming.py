"""Synthetic diagnostic for the PyVNCServer 3.6 adaptive controller/cache."""

from __future__ import annotations

import argparse
import time

from pyvncserver.runtime.adaptive import (
    AdaptiveStreamConfig,
    AdaptiveStreamController,
    EncodedRegionCache,
)


def run_controller() -> None:
    config = AdaptiveStreamConfig(ewma_alpha=0.35)
    controller = AdaptiveStreamController(60, config)
    phases = [
        ("healthy", 0.006, 0.001, 250_000, 2_000_000, 20),
        ("cpu-bound", 0.030, 0.002, 350_000, 2_000_000, 15),
        ("network-bound", 0.045, 0.036, 350_000, 2_000_000, 15),
        ("recovery", 0.005, 0.001, 220_000, 2_000_000, 30),
    ]

    print("Adaptive controller")
    print("phase          fps   total  network cpu    order")
    for name, total, send, encoded, original, samples in phases:
        for _ in range(samples):
            snapshot = controller.observe(total, encoded, original, send_time=send)
        order = controller.recommended_encoding_order([7, 16, 6, 5, 2, 0, 21])
        print(
            f"{name:13} {snapshot.target_fps:5.1f} "
            f"{snapshot.pressure:6.2f} {snapshot.network_pressure:7.2f} "
            f"{snapshot.cpu_pressure:5.2f}  {order}"
        )


def run_cache(iterations: int) -> None:
    cache = EncodedRegionCache(max_entries=128, max_bytes=8 * 1024 * 1024)
    pixels = (b"\x10\x20\x30\x00" * (128 * 128))
    key = cache.make_key(5, pixels, 128, 128, 4, {"bits_per_pixel": 32})
    cache.put(key, b"encoded-hextile" * 64)
    start = time.perf_counter()
    for _ in range(iterations):
        assert cache.get(key) is not None
    elapsed = time.perf_counter() - start
    print("\nEncoded-region cache")
    print(f"lookups: {iterations}")
    print(f"elapsed: {elapsed * 1000:.2f} ms")
    print(f"lookups/s: {iterations / max(elapsed, 1e-9):,.0f}")
    print(f"stats: {cache.stats}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-lookups", type=int, default=100_000)
    args = parser.parse_args()
    run_controller()
    run_cache(max(1, args.cache_lookups))


if __name__ == "__main__":
    main()

