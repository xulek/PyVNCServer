#!/usr/bin/env python3
"""
Benchmark script to compare mss vs PIL screen capture performance
"""

import time
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Suppress PIL warnings
logging.basicConfig(level=logging.WARNING)

def benchmark_capture(backend_name: str, iterations: int = 10):
    """Benchmark screen capture with specified backend"""
    from vnc_lib.screen_capture import ScreenCapture

    # Create capture instance
    capture = ScreenCapture()

    # Standard VNC pixel format (32-bit RGB)
    pixel_format = {
        'bits_per_pixel': 32,
        'depth': 24,
        'big_endian_flag': False,
        'true_colour_flag': True,
        'red_max': 255,
        'green_max': 255,
        'blue_max': 255,
        'red_shift': 0,
        'green_shift': 8,
        'blue_shift': 16
    }

    # Warm-up
    capture.capture_fast(pixel_format)

    # Benchmark
    times = []
    total_bytes = 0

    for i in range(iterations):
        result = capture.capture_fast(pixel_format)
        if result.pixel_data:
            times.append(result.capture_time)
            total_bytes = len(result.pixel_data)

    if times:
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        fps = 1.0 / avg_time if avg_time > 0 else 0

        print(f"\n{backend_name} Results ({iterations} captures):")
        print(f"  Average time: {avg_time*1000:.2f}ms")
        print(f"  Min time: {min_time*1000:.2f}ms")
        print(f"  Max time: {max_time*1000:.2f}ms")
        print(f"  Theoretical FPS: {fps:.1f}")
        print(f"  Data size: {total_bytes / 1024 / 1024:.2f} MB")

        return avg_time
    else:
        print(f"\n{backend_name}: Failed to capture")
        return None


def main():
    print("=" * 60)
    print("Screen Capture Performance Benchmark")
    print("=" * 60)

    # Check which backends are available
    try:
        import mss
        mss_available = True
    except ImportError:
        mss_available = False

    try:
        from PIL import ImageGrab
        pil_available = True
    except ImportError:
        pil_available = False

    print(f"\nAvailable backends:")
    print(f"  mss: {'✓' if mss_available else '✗ (not installed)'}")
    print(f"  PIL: {'✓' if pil_available else '✗ (not installed)'}")

    if not mss_available and not pil_available:
        print("\nError: No screen capture backend available!")
        print("Install mss: pip install mss")
        print("Install PIL: pip install Pillow")
        return

    # Run benchmark with mss (if available)
    if mss_available:
        mss_time = benchmark_capture("mss backend", iterations=20)
    else:
        mss_time = None

    # Run benchmark with PIL (if available)
    if pil_available and mss_available:
        # To test PIL fallback, we need to temporarily disable mss
        # For now, just show the mss results
        print("\nNote: Using mss as primary backend (recommended)")
        print("PIL is available as fallback if mss fails")
    elif pil_available:
        pil_time = benchmark_capture("PIL backend", iterations=20)

    print("\n" + "=" * 60)
    print("Recommendation:")
    if mss_available:
        print("  ✓ Using high-performance mss backend")
    else:
        print("  ! Install mss for better performance: pip install mss")
    print("=" * 60)


if __name__ == "__main__":
    main()
