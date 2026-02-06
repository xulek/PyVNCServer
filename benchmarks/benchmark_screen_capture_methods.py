#!/usr/bin/env python3
"""
Comprehensive Screen Capture Performance Benchmark

Tests multiple capture backends on Windows and measures:
- Raw capture time (grab pixels from screen)
- BGRA-to-RGB conversion time
- Full pipeline time (capture + convert to VNC pixel format)

Usage: python benchmarks/benchmark_screen_capture_methods.py [iterations]
"""

import time
import sys
import statistics
import ctypes
import ctypes.wintypes
import struct


# Standard VNC pixel format (32-bit RGB0)
PIXEL_FORMAT = {
    'bits_per_pixel': 32,
    'depth': 24,
    'big_endian_flag': 0,
    'true_colour_flag': 1,
    'red_max': 255,
    'green_max': 255,
    'blue_max': 255,
    'red_shift': 0,
    'green_shift': 8,
    'blue_shift': 16,
}


def print_stats(name: str, times_ms: list[float], data_size: int = 0):
    """Print statistics for a benchmark"""
    if not times_ms:
        print(f"  {name}: No data")
        return
    sorted_t = sorted(times_ms)
    avg = statistics.mean(times_ms)
    fps = 1000.0 / avg if avg > 0 else 0
    p50 = statistics.median(times_ms)
    p95 = sorted_t[int(len(sorted_t) * 0.95)] if len(sorted_t) >= 20 else sorted_t[-1]
    p99 = sorted_t[int(len(sorted_t) * 0.99)] if len(sorted_t) >= 100 else sorted_t[-1]

    print(f"  {name}:")
    print(f"    Min:  {min(times_ms):.2f} ms")
    print(f"    Avg:  {avg:.2f} ms  ({fps:.1f} theoretical FPS)")
    print(f"    P50:  {p50:.2f} ms")
    print(f"    P95:  {p95:.2f} ms")
    if len(sorted_t) >= 100:
        print(f"    P99:  {p99:.2f} ms")
    print(f"    Max:  {max(times_ms):.2f} ms")
    if data_size:
        print(f"    Data: {data_size / 1024 / 1024:.2f} MB")


def benchmark_mss(iterations: int):
    """Benchmark mss (GDI via ctypes)"""
    try:
        import mss
    except ImportError:
        print("\n[mss] Not installed (pip install mss)")
        return

    print(f"\n[mss] GDI-based capture via ctypes")
    sct = mss.mss()
    monitor = sct.monitors[0]  # All monitors / primary
    print(f"  Monitor: {monitor['width']}x{monitor['height']}")

    # Warm up
    for _ in range(3):
        sct.grab(monitor)

    # Benchmark raw capture (BGRA)
    raw_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img = sct.grab(monitor)
        elapsed = (time.perf_counter() - t0) * 1000
        raw_times.append(elapsed)

    bgra_size = len(img.raw)
    width, height = img.width, img.height
    print_stats("Raw BGRA capture", raw_times, bgra_size)

    # Benchmark BGRA->RGB conversion (memoryview approach from screen_capture.py)
    conv_times = []
    num_pixels = width * height
    rgb_buffer = bytearray(num_pixels * 3)
    for _ in range(iterations):
        img = sct.grab(monitor)
        bgra_bytes = img.raw

        t0 = time.perf_counter()
        bgra_view = memoryview(bgra_bytes)
        rgb_view = memoryview(rgb_buffer)
        rgb_view[0::3] = bgra_view[2::4]  # R
        rgb_view[1::3] = bgra_view[1::4]  # G
        rgb_view[2::3] = bgra_view[0::4]  # B
        elapsed = (time.perf_counter() - t0) * 1000
        conv_times.append(elapsed)

    print_stats("BGRA->RGB conversion", conv_times)

    # Benchmark full pipeline (capture + convert to VNC format)
    pixel_buffer = bytearray(num_pixels * 4)
    full_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img = sct.grab(monitor)
        bgra_bytes = img.raw
        # BGRA -> RGB
        bgra_view = memoryview(bgra_bytes)
        rgb_view2 = memoryview(rgb_buffer)
        rgb_view2[0::3] = bgra_view[2::4]
        rgb_view2[1::3] = bgra_view[1::4]
        rgb_view2[2::3] = bgra_view[0::4]
        # RGB -> RGB0 (VNC 32-bit)
        pix_view = memoryview(pixel_buffer)
        rgb_view3 = memoryview(rgb_buffer)
        pix_view[0::4] = rgb_view3[0::3]
        pix_view[1::4] = rgb_view3[1::3]
        pix_view[2::4] = rgb_view3[2::3]
        elapsed = (time.perf_counter() - t0) * 1000
        full_times.append(elapsed)

    print_stats("Full pipeline (capture+RGB0)", full_times, num_pixels * 4)

    # Benchmark BGRA->RGB0 DIRECT (skip intermediate RGB step)
    direct_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img = sct.grab(monitor)
        bgra_bytes = img.raw
        bgra_view = memoryview(bgra_bytes)
        pix_view = memoryview(pixel_buffer)
        # BGRA -> RGB0 directly (B->pos2, G->pos1, R->pos0, skip A)
        pix_view[0::4] = bgra_view[2::4]  # R
        pix_view[1::4] = bgra_view[1::4]  # G
        pix_view[2::4] = bgra_view[0::4]  # B
        # pix_view[3::4] already 0 (padding)
        elapsed = (time.perf_counter() - t0) * 1000
        direct_times.append(elapsed)

    print_stats("BGRA->RGB0 DIRECT (skip RGB step)", direct_times, num_pixels * 4)

    sct.close()


def benchmark_pil(iterations: int):
    """Benchmark PIL/ImageGrab"""
    try:
        from PIL import ImageGrab
    except ImportError:
        print("\n[PIL] Not installed (pip install Pillow)")
        return

    print(f"\n[PIL/ImageGrab] GDI-based capture")

    # Warm up
    for _ in range(3):
        ImageGrab.grab()

    raw_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img = ImageGrab.grab()
        elapsed = (time.perf_counter() - t0) * 1000
        raw_times.append(elapsed)

    width, height = img.size
    print(f"  Resolution: {width}x{height}")
    print_stats("Raw capture (PIL Image)", raw_times)

    # Benchmark with tobytes conversion
    full_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img = ImageGrab.grab()
        rgb_bytes = img.tobytes()
        elapsed = (time.perf_counter() - t0) * 1000
        full_times.append(elapsed)

    print_stats("Capture + tobytes()", full_times, len(rgb_bytes))


def benchmark_dxcam(iterations: int):
    """Benchmark DXcam (DXGI Desktop Duplication)"""
    try:
        import dxcam
    except ImportError:
        print("\n[dxcam] Not installed (pip install dxcam)")
        return

    print(f"\n[dxcam] DXGI Desktop Duplication API")

    camera = dxcam.create()
    # Single grab test
    frame = camera.grab()
    if frame is None:
        # DXcam returns None if no frame change; force a grab
        camera.start(target_fps=120)
        time.sleep(0.1)
        frame = camera.get_latest_frame()
        camera.stop()

    if frame is not None:
        print(f"  Resolution: {frame.shape[1]}x{frame.shape[0]}")
        print(f"  Format: numpy {frame.dtype}, shape {frame.shape}")

    raw_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        frame = camera.grab()
        elapsed = (time.perf_counter() - t0) * 1000
        if frame is not None:
            raw_times.append(elapsed)

    if raw_times:
        print_stats("Single grab()", raw_times)
    else:
        print("  Warning: No frames captured (screen may be static)")

    # Benchmark continuous capture mode
    camera.start(target_fps=240)
    time.sleep(0.5)  # Let it warm up

    cont_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        frame = camera.get_latest_frame()
        elapsed = (time.perf_counter() - t0) * 1000
        if frame is not None:
            cont_times.append(elapsed)

    camera.stop()

    if cont_times:
        print_stats("Continuous get_latest_frame()", cont_times)

    del camera


def benchmark_bettercam(iterations: int):
    """Benchmark BetterCam (DXGI Desktop Duplication, DXcam fork)"""
    try:
        import bettercam
    except ImportError:
        print("\n[bettercam] Not installed (pip install bettercam)")
        return

    print(f"\n[bettercam] DXGI Desktop Duplication (DXcam fork)")

    camera = bettercam.create()
    frame = camera.grab()
    if frame is not None:
        print(f"  Resolution: {frame.shape[1]}x{frame.shape[0]}")

    raw_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        frame = camera.grab()
        elapsed = (time.perf_counter() - t0) * 1000
        if frame is not None:
            raw_times.append(elapsed)

    if raw_times:
        print_stats("Single grab()", raw_times)

    del camera


def benchmark_win32_gdi_ctypes(iterations: int):
    """Benchmark raw Win32 GDI via ctypes (no external deps)"""
    if sys.platform != 'win32':
        print("\n[Win32 GDI ctypes] Windows only")
        return

    print(f"\n[Win32 GDI ctypes] Direct GDI capture (zero dependencies)")

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Get screen dimensions
    width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
    print(f"  Resolution: {width}x{height}")

    # BITMAPINFOHEADER
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.wintypes.DWORD),
            ("biWidth", ctypes.wintypes.LONG),
            ("biHeight", ctypes.wintypes.LONG),
            ("biPlanes", ctypes.wintypes.WORD),
            ("biBitCount", ctypes.wintypes.WORD),
            ("biCompression", ctypes.wintypes.DWORD),
            ("biSizeImage", ctypes.wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.wintypes.LONG),
            ("biYPelsPerMeter", ctypes.wintypes.LONG),
            ("biClrUsed", ctypes.wintypes.DWORD),
            ("biClrImportant", ctypes.wintypes.DWORD),
        ]

    # Setup
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height  # Top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32  # BGRA
    bmi.biCompression = 0  # BI_RGB

    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(
        hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
    )
    gdi32.SelectObject(hdc_mem, hbmp)

    SRCCOPY = 0x00CC0020
    data_size = width * height * 4

    # Warm up
    for _ in range(3):
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)

    # Benchmark raw BitBlt (no data copy)
    blt_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)
        elapsed = (time.perf_counter() - t0) * 1000
        blt_times.append(elapsed)

    print_stats("BitBlt only (GPU->DIB)", blt_times)

    # Benchmark BitBlt + ctypes.memmove to buffer
    buffer = bytearray(data_size)
    buffer_ptr = (ctypes.c_char * data_size).from_buffer(buffer)
    copy_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)
        ctypes.memmove(buffer_ptr, bits, data_size)
        elapsed = (time.perf_counter() - t0) * 1000
        copy_times.append(elapsed)

    print_stats("BitBlt + memmove to buffer", copy_times, data_size)

    # Benchmark full pipeline: BitBlt + memmove + BGRA->RGB0
    num_pixels = width * height
    pixel_buffer = bytearray(num_pixels * 4)
    full_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)
        ctypes.memmove(buffer_ptr, bits, data_size)
        # BGRA -> RGB0 direct
        bgra_view = memoryview(buffer)
        pix_view = memoryview(pixel_buffer)
        pix_view[0::4] = bgra_view[2::4]  # R
        pix_view[1::4] = bgra_view[1::4]  # G
        pix_view[2::4] = bgra_view[0::4]  # B
        elapsed = (time.perf_counter() - t0) * 1000
        full_times.append(elapsed)

    print_stats("Full pipeline (BitBlt+copy+RGB0)", full_times, num_pixels * 4)

    # Optimization idea: skip channel swap if client accepts BGR
    bgr_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)
        ctypes.memmove(buffer_ptr, bits, data_size)
        # BGRA is already BGR0 if client uses blue_shift=0, green_shift=8, red_shift=16
        # Zero-copy: just use the buffer as-is!
        elapsed = (time.perf_counter() - t0) * 1000
        bgr_times.append(elapsed)

    print_stats("BitBlt+copy (BGR0 zero-swap)", bgr_times, data_size)

    # Cleanup
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def main():
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    print("=" * 65)
    print("Screen Capture Performance Benchmark")
    print(f"Iterations: {iterations}")
    print("=" * 65)

    # Always test these (no or minimal deps)
    benchmark_win32_gdi_ctypes(iterations)
    benchmark_mss(iterations)
    benchmark_pil(iterations)

    # Optional DXGI-based backends
    benchmark_dxcam(iterations)
    benchmark_bettercam(iterations)

    print("\n" + "=" * 65)
    print("KEY INSIGHT: If VNC client requests BGR pixel format")
    print("(red_shift=16, blue_shift=0), the BGRA capture data can be")
    print("used directly as BGR0 with ZERO channel swapping.")
    print("=" * 65)


if __name__ == "__main__":
    main()
