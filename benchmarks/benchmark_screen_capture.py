#!/usr/bin/env python3
"""
Benchmark script to compare available screen capture backends.
"""

import time
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Suppress PIL warnings
logging.basicConfig(level=logging.WARNING)

def benchmark_capture(
    backend_name: str,
    backend_preference: str,
    pixel_format_name: str,
    pixel_format: dict,
    iterations: int = 10,
):
    """Benchmark screen capture with specified backend"""
    from vnc_lib.screen_capture import ScreenCapture

    # Create capture instance
    capture = ScreenCapture(backend_preference=backend_preference)

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

        print(f"\n{backend_name} [{pixel_format_name}] Results ({iterations} captures):")
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

    bgr0_format = {
        'bits_per_pixel': 32,
        'depth': 24,
        'big_endian_flag': False,
        'true_colour_flag': True,
        'red_max': 255,
        'green_max': 255,
        'blue_max': 255,
        'red_shift': 16,
        'green_shift': 8,
        'blue_shift': 0,
    }
    rgb0_format = {
        'bits_per_pixel': 32,
        'depth': 24,
        'big_endian_flag': False,
        'true_colour_flag': True,
        'red_max': 255,
        'green_max': 255,
        'blue_max': 255,
        'red_shift': 0,
        'green_shift': 8,
        'blue_shift': 16,
    }

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

    try:
        import dxcam  # noqa: F401
        dxcam_available = True
    except ImportError:
        dxcam_available = False

    print(f"\nAvailable backends:")
    print(f"  dxcam: {'yes' if dxcam_available else 'no (not installed)'}")
    print(f"  mss:   {'yes' if mss_available else 'no (not installed)'}")
    print(f"  PIL:   {'yes' if pil_available else 'no (not installed)'}")

    if not dxcam_available and not mss_available and not pil_available:
        print("\nError: No screen capture backend available!")
        print("Install dxcam: pip install dxcam")
        print("Install mss: pip install mss")
        print("Install PIL: pip install Pillow")
        return

    if dxcam_available:
        benchmark_capture("dxcam backend", "dxcam", "BGR0/native", bgr0_format, iterations=20)
        benchmark_capture("dxcam backend", "dxcam", "RGB0", rgb0_format, iterations=20)

    # Run benchmark with mss (if available)
    if mss_available:
        benchmark_capture("mss backend", "mss", "BGR0/native", bgr0_format, iterations=20)
        benchmark_capture("mss backend", "mss", "RGB0", rgb0_format, iterations=20)

    if pil_available:
        benchmark_capture("PIL backend", "pil", "RGB0", rgb0_format, iterations=20)

    print("\n" + "=" * 60)
    print("Recommendation:")
    if dxcam_available:
        print("  dxcam is available: test it if you want a real DXGI/Desktop Duplication path.")
    if mss_available:
        print("  mss is available and remains the safest default backend.")
    else:
        print("  Install mss for better performance: pip install mss")
    print("=" * 60)


if __name__ == "__main__":
    main()
