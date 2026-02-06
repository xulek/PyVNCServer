#!/usr/bin/env python3
"""
Python 3.13 Features Demonstration for PyVNCServer
==================================================

This script demonstrates all the Python 3.13 enhancements in the VNC server:

1. Pattern Matching (match/case) - PEP 634
2. Generic Type Parameters - PEP 695
3. Exception Groups - PEP 654
4. Type Aliases with 'type' statement
5. Enhanced Type Narrowing
6. Improved Error Messages

Run with: python3.13 examples/python313_features_demo.py
"""

import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vnc_lib.metrics import SlidingWindow
from vnc_lib.exceptions import (
    VNCError, ProtocolError, AuthenticationError,
    ExceptionCollector, categorize_exceptions
)
from vnc_lib.types import (
    Result, Ok, Err, PixelFormat,
    is_valid_dimension, narrow_bytes
)
from vnc_lib.desktop_resize import (
    Screen, DesktopSizeHandler,
    create_single_screen_layout, create_dual_screen_layout
)
from vnc_lib.encodings import EncoderManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def demo_pattern_matching():
    """
    Demonstration 1: Pattern Matching (PEP 634)
    Python 3.13 enhanced pattern matching for cleaner code
    """
    print("\n" + "="*70)
    print("DEMO 1: Pattern Matching (match/case)")
    print("="*70)

    # Simulate different message types
    message_types = [0, 2, 3, 4, 5, 99]

    for msg_type in message_types:
        match msg_type:
            case 0:
                print(f"  {msg_type} -> SetPixelFormat message")
            case 2:
                print(f"  {msg_type} -> SetEncodings message")
            case 3:
                print(f"  {msg_type} -> FramebufferUpdateRequest")
            case 4:
                print(f"  {msg_type} -> KeyEvent")
            case 5:
                print(f"  {msg_type} -> PointerEvent")
            case _:
                print(f"  {msg_type} -> Unknown message type")

    # Pattern matching with encoding selection
    print("\n  Encoding selection with pattern matching:")
    encoder_manager = EncoderManager()

    for content_type in ["static", "dynamic", "scrolling"]:
        client_encodings = {0, 1, 2, 5, 16}  # All encodings supported

        match content_type:
            case "static":
                print(f"    {content_type}: Prefer compression (ZRLE)")
            case "dynamic":
                print(f"    {content_type}: Prefer speed (Hextile)")
            case "scrolling":
                print(f"    {content_type}: Prefer CopyRect")
            case _:
                print(f"    {content_type}: Default balance")

        enc_type, encoder = encoder_manager.get_best_encoder(
            client_encodings, content_type
        )
        print(f"      -> Selected encoding: {enc_type} ({type(encoder).__name__})")


def demo_generic_types():
    """
    Demonstration 2: Generic Type Parameters (PEP 695)
    Python 3.13 simplified generic syntax
    """
    print("\n" + "="*70)
    print("DEMO 2: Generic Type Parameters (PEP 695)")
    print("="*70)

    # SlidingWindow with float type
    fps_window: SlidingWindow[float] = SlidingWindow(maxlen=10)

    print("  Adding FPS values to SlidingWindow[float]:")
    for fps in [60.0, 58.5, 59.2, 61.0, 57.8, 60.5, 59.9, 60.1, 58.8, 60.3]:
        fps_window.add(fps)
        print(f"    Added {fps:.1f} FPS")

    print(f"\n  Statistics:")
    print(f"    Average: {fps_window.average():.2f} FPS")
    print(f"    Min: {fps_window.min():.2f} FPS")
    print(f"    Max: {fps_window.max():.2f} FPS")
    print(f"    Median: {fps_window.median():.2f} FPS")
    print(f"    95th percentile: {fps_window.percentile(95):.2f} FPS")

    # SlidingWindow with int type
    frame_sizes: SlidingWindow[int] = SlidingWindow(maxlen=5)

    print("\n  Adding frame sizes to SlidingWindow[int]:")
    for size in [1024, 2048, 1536, 2200, 1890]:
        frame_sizes.add(size)
        print(f"    Added {size} bytes")

    print(f"\n  Statistics:")
    print(f"    Average: {frame_sizes.average():.0f} bytes")
    print(f"    Min: {frame_sizes.min()} bytes")
    print(f"    Max: {frame_sizes.max()} bytes")


def demo_exception_groups():
    """
    Demonstration 3: Exception Groups (PEP 654)
    Better error handling for multiple failures
    """
    print("\n" + "="*70)
    print("DEMO 3: Exception Groups (PEP 654)")
    print("="*70)

    # Simulate multiple operations that can fail
    operations = [
        ("client_1", lambda: raise_if(True, ProtocolError("Version mismatch"))),
        ("client_2", lambda: raise_if(False, AuthenticationError("Bad password"))),
        ("client_3", lambda: raise_if(True, AuthenticationError("Invalid challenge"))),
        ("client_4", lambda: raise_if(False, ProtocolError("Parse error"))),
        ("client_5", lambda: raise_if(True, VNCError("Generic error"))),
    ]

    print("  Collecting exceptions from multiple clients:")
    with ExceptionCollector() as collector:
        for name, operation in operations:
            with collector.catch(name):
                operation()
                print(f"    ✓ {name} succeeded")

    if collector.has_exceptions():
        exc_group = collector.create_exception_group("Multiple client errors")

        print(f"\n  {len(exc_group.exceptions)} errors occurred:")

        # Categorize by type
        categories = categorize_exceptions(exc_group)

        for exc_type, exceptions in categories.items():
            print(f"\n    {exc_type}: {len(exceptions)} occurrence(s)")
            for exc in exceptions:
                # Get the note added by ExceptionCollector
                notes = getattr(exc, '__notes__', [])
                note_str = f" ({notes[0]})" if notes else ""
                print(f"      - {exc}{note_str}")


def demo_result_type():
    """
    Demonstration 4: Result Type
    Functional error handling without exceptions
    """
    print("\n" + "="*70)
    print("DEMO 4: Result Type for Error Handling")
    print("="*70)

    def divide(a: float, b: float) -> Result[float, str]:
        """Division with Result type"""
        if b == 0:
            return Err("Division by zero")
        return Ok(a / b)

    def validate_dimensions(width: int, height: int) -> Result[tuple[int, int], str]:
        """Validate screen dimensions"""
        if not is_valid_dimension(width, height):
            return Err(f"Invalid dimensions: {width}x{height}")
        return Ok((width, height))

    print("  Division examples:")
    for a, b in [(10, 2), (5, 0), (100, 4)]:
        result = divide(a, b)
        if result.is_ok():
            print(f"    {a} / {b} = {result.unwrap()}")
        else:
            print(f"    {a} / {b} = Error: {result.unwrap_err()}")

    print("\n  Dimension validation:")
    test_dims = [(1920, 1080), (-100, 200), (0, 0), (65536, 1000)]

    for width, height in test_dims:
        result = validate_dimensions(width, height)
        if result.is_ok():
            w, h = result.unwrap()
            print(f"    ✓ {w}x{h} is valid")
        else:
            print(f"    ✗ {result.unwrap_err()}")


def demo_desktop_resize():
    """
    Demonstration 5: Desktop Resize with Pattern Matching
    Dynamic screen size management
    """
    print("\n" + "="*70)
    print("DEMO 5: Desktop Resize Support")
    print("="*70)

    handler = DesktopSizeHandler()
    handler.supports_extended = True
    handler.initialize(1920, 1080)

    print(f"  Initial size: {handler.current_width}x{handler.current_height}")

    # Test different resize scenarios
    resize_requests = [
        (2560, 1440, handler.REASON_CLIENT, "Client requested larger screen"),
        (-100, 200, handler.REASON_CLIENT, "Invalid negative dimension"),
        (1024, 768, handler.REASON_SERVER, "Server resize to smaller screen"),
        (0, 0, handler.REASON_OTHER, "Invalid zero dimensions"),
    ]

    print("\n  Resize requests:")
    for width, height, reason, description in resize_requests:
        print(f"    {description}: {width}x{height}")

        status, data = handler.handle_resize_event(width, height, reason)

        match status:
            case handler.STATUS_NO_ERROR:
                print(f"      ✓ {handler.get_status_message(status)}")
                print(f"      New size: {handler.current_width}x{handler.current_height}")
            case handler.STATUS_INVALID_SCREEN_LAYOUT:
                print(f"      ✗ {handler.get_status_message(status)}")
            case handler.STATUS_OUT_OF_RESOURCES:
                print(f"      ✗ {handler.get_status_message(status)}")

    # Multi-screen setup
    print("\n  Multi-screen configuration:")
    screens = create_dual_screen_layout(1920, 1080, 1920, 1080, horizontal=True)

    for screen in screens:
        handler.add_screen(screen)
        print(f"    Screen {screen.id}: {screen.width}x{screen.height} at ({screen.x}, {screen.y})")

    total_width, total_height = handler.get_total_dimensions()
    print(f"    Total bounding box: {total_width}x{total_height}")


def demo_type_narrowing():
    """
    Demonstration 6: Type Narrowing
    Python 3.13 enhanced type narrowing with pattern matching
    """
    print("\n" + "="*70)
    print("DEMO 6: Type Narrowing with Pattern Matching")
    print("="*70)

    # Test with different data types
    test_data = [
        b"Hello, VNC!",
        bytearray(b"Pixel data"),
        memoryview(b"Screen buffer"),
    ]

    print("  Converting various byte-like types to bytes:")
    for data in test_data:
        original_type = type(data).__name__
        result = narrow_bytes(data)
        print(f"    {original_type:12} -> bytes: {result[:20]!r}")

    # Dimension validation
    print("\n  Validating dimensions:")
    test_sizes = [
        (1920, 1080),
        (800, 600),
        (65536, 1000),
        (-100, 200),
    ]

    for width, height in test_sizes:
        try:
            w = narrow_positive_int(width, "width")
            h = narrow_positive_int(height, "height")
            if is_valid_dimension(w, h):
                print(f"    ✓ {w}x{h} is valid")
            else:
                print(f"    ✗ {w}x{h} exceeds maximum size")
        except ValueError as e:
            print(f"    ✗ {width}x{height}: {e}")


# Helper functions
def raise_if(condition: bool, exception: Exception):
    """Raise exception if condition is True"""
    if condition:
        raise exception


def main():
    """Run all demonstrations"""
    print("\n" + "="*70)
    print("Python 3.13 Features in PyVNCServer - Interactive Demo")
    print("="*70)
    print("\nThis demo showcases the modern Python features used in v3.0:")
    print("  • Pattern matching (match/case)")
    print("  • Generic type parameters (class[T])")
    print("  • Exception groups (ExceptionGroup)")
    print("  • Type aliases (type X = Y)")
    print("  • Enhanced type narrowing")
    print("  • Result types for functional error handling")

    try:
        demo_pattern_matching()
        demo_generic_types()
        demo_exception_groups()
        demo_result_type()
        demo_desktop_resize()
        demo_type_narrowing()

        print("\n" + "="*70)
        print("All demonstrations completed successfully!")
        print("="*70)

    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
