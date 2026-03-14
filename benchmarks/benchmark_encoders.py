#!/usr/bin/env python3
"""
Microbenchmark Raw/Zlib/Tight/ZRLE encoder throughput on synthetic frame data.

Usage:
    python benchmarks/benchmark_encoders.py
"""

from __future__ import annotations

import statistics
import time

from vnc_lib.encodings import RawEncoder, ZRLEEncoder, ZlibEncoder
from vnc_lib.tight_encoding import TightEncoder


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


def make_gradient(width: int, height: int) -> bytes:
    buf = bytearray()
    for y in range(height):
        for x in range(width):
            buf.extend((
                (x * 5) & 0xFF,          # B
                (y * 3) & 0xFF,          # G
                ((x + y) * 2) & 0xFF,    # R
                0,
            ))
    return bytes(buf)


def make_ui_pattern(width: int, height: int) -> bytes:
    palette = (
        (32, 32, 32, 0),
        (64, 64, 64, 0),
        (200, 200, 200, 0),
        (255, 255, 255, 0),
        (180, 120, 40, 0),
        (30, 90, 180, 0),
    )
    buf = bytearray()
    for y in range(height):
        stripe = (y // 8) % len(palette)
        for x in range(width):
            block = ((x // 16) + stripe) % len(palette)
            buf.extend(palette[block])
    return bytes(buf)


def benchmark_encoder(name: str, encoder, pixel_data: bytes, width: int, height: int,
                      bytes_per_pixel: int, iterations: int = 8) -> dict[str, float]:
    timings_ms: list[float] = []
    encoded_sizes: list[int] = []

    for _ in range(iterations):
        start = time.perf_counter()
        if name == "ZRLE":
            encoded = encoder.encode(
                pixel_data,
                width,
                height,
                bytes_per_pixel,
                pixel_format=NATIVE_BGR0,
            )
        else:
            encoded = encoder.encode(pixel_data, width, height, bytes_per_pixel)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings_ms.append(elapsed_ms)
        encoded_sizes.append(len(encoded))

    return {
        "avg_ms": statistics.mean(timings_ms),
        "min_ms": min(timings_ms),
        "max_ms": max(timings_ms),
        "avg_size": statistics.mean(encoded_sizes),
    }


def print_case(case_name: str, pixel_data: bytes, width: int, height: int) -> None:
    print(f"\n[{case_name}] {width}x{height}")
    raw = RawEncoder()
    zlib_encoder = ZlibEncoder(compression_level=3)
    tight = TightEncoder(compression_level=6)
    zrle = ZRLEEncoder(compression_level=3)

    results = {
        "Raw": benchmark_encoder("Raw", raw, pixel_data, width, height, 4),
        "Zlib": benchmark_encoder("Zlib", zlib_encoder, pixel_data, width, height, 4),
        "Tight": benchmark_encoder("Tight", tight, pixel_data, width, height, 4),
        "ZRLE": benchmark_encoder("ZRLE", zrle, pixel_data, width, height, 4),
    }

    original_size = len(pixel_data)
    for name in ("Raw", "Zlib", "Tight", "ZRLE"):
        stats = results[name]
        ratio = original_size / max(1.0, stats["avg_size"])
        print(
            f"{name:>5}  avg={stats['avg_ms']:7.2f} ms"
            f"  min={stats['min_ms']:7.2f} ms"
            f"  max={stats['max_ms']:7.2f} ms"
            f"  size={stats['avg_size']:10.0f} B"
            f"  ratio={ratio:6.2f}x"
        )


def main() -> None:
    print("PyVNCServer encoder microbenchmark")
    print_case("UI-like", make_ui_pattern(512, 256), 512, 256)
    print_case("Gradient", make_gradient(512, 256), 512, 256)
    print_case("UI-like region", make_ui_pattern(256, 128), 256, 128)


if __name__ == "__main__":
    main()
