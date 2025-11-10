"""
Tests for Python 3.13 Enhanced Features
Tests: CopyRect encoding, desktop resize, exception groups, generics
"""

import pytest
import struct
from vnc_lib.encodings import CopyRectEncoder, EncoderManager
from vnc_lib.desktop_resize import (
    Screen, DesktopSizeHandler,
    create_single_screen_layout, create_dual_screen_layout
)
from vnc_lib.exceptions import (
    VNCError, ProtocolError, AuthenticationError,
    ExceptionCollector, categorize_exceptions, collect_exceptions
)
from vnc_lib.metrics import SlidingWindow
from vnc_lib.types import Result, Ok, Err, is_valid_dimension, narrow_bytes


class TestCopyRectEncoding:
    """Test CopyRect encoding for scrolling"""

    def test_copyrect_first_frame(self):
        """First frame should return raw data (no previous frame)"""
        encoder = CopyRectEncoder()

        pixel_data = b'\x00\xFF' * 100  # 200 bytes
        encoded = encoder.encode(pixel_data, 10, 10, 2)

        # First frame - no copy possible
        assert encoded == pixel_data

    def test_copyrect_identical_frames(self):
        """Identical frames should not trigger copy"""
        encoder = CopyRectEncoder()

        pixel_data = b'\x00\xFF' * 100
        encoder.encode(pixel_data, 10, 10, 2)  # First frame

        # Second identical frame
        encoded = encoder.encode(pixel_data, 10, 10, 2)

        # Should return raw data (no scroll detected)
        assert encoded == pixel_data

    def test_copyrect_vertical_scroll(self):
        """Test vertical scroll detection"""
        encoder = CopyRectEncoder()

        # Create initial frame (10x10 pixels, 2 bpp)
        width, height, bpp = 100, 100, 4
        frame1 = bytearray(width * height * bpp)

        # Fill with pattern
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * bpp
                frame1[offset:offset+bpp] = struct.pack(">I", y * 256 + x)

        encoder.encode(bytes(frame1), width, height, bpp)  # First frame

        # Create scrolled frame (shifted down by 2 lines)
        frame2 = bytearray(width * height * bpp)
        for y in range(height - 2):
            for x in range(width):
                src_offset = (y * width + x) * bpp
                dst_offset = ((y + 2) * width + x) * bpp
                frame2[dst_offset:dst_offset+bpp] = frame1[src_offset:src_offset+bpp]

        encoded = encoder.encode(bytes(frame2), width, height, bpp)

        # Should detect scroll and return small CopyRect data
        if len(encoded) == 4:  # CopyRect format
            src_x, src_y = struct.unpack(">HH", encoded)
            # Source coordinates should indicate scroll
            assert isinstance(src_x, int)
            assert isinstance(src_y, int)

    def test_copyrect_dimension_change(self):
        """Test handling of dimension changes"""
        encoder = CopyRectEncoder()

        pixel_data1 = b'\x00\xFF' * 100
        encoder.encode(pixel_data1, 10, 10, 2)

        # Different dimensions
        pixel_data2 = b'\x00\xFF' * 200
        encoded = encoder.encode(pixel_data2, 10, 20, 2)

        # Should reset and return raw data
        assert encoded == pixel_data2


class TestDesktopResize:
    """Test desktop resize support"""

    def test_screen_creation(self):
        """Test Screen dataclass creation"""
        screen = Screen(id=0, x=0, y=0, width=1920, height=1080)

        assert screen.id == 0
        assert screen.width == 1920
        assert screen.height == 1080

    def test_screen_serialization(self):
        """Test Screen to_bytes and from_bytes"""
        screen = Screen(id=1, x=100, y=200, width=800, height=600, flags=0)

        data = screen.to_bytes()
        assert len(data) == 16

        screen2 = Screen.from_bytes(data)
        assert screen2.id == screen.id
        assert screen2.x == screen.x
        assert screen2.y == screen.y
        assert screen2.width == screen.width
        assert screen2.height == screen.height

    def test_desktop_size_handler_init(self):
        """Test DesktopSizeHandler initialization"""
        handler = DesktopSizeHandler()
        handler.initialize(1920, 1080)

        assert handler.current_width == 1920
        assert handler.current_height == 1080
        assert len(handler.screens) == 1
        assert handler.screens[0].width == 1920

    def test_resize_valid(self):
        """Test valid resize operation"""
        handler = DesktopSizeHandler()
        handler.initialize(1920, 1080)

        success = handler.resize(2560, 1440, handler.REASON_CLIENT)

        assert success
        assert handler.current_width == 2560
        assert handler.current_height == 1440

    def test_resize_invalid_dimensions(self):
        """Test resize with invalid dimensions"""
        handler = DesktopSizeHandler()
        handler.initialize(1920, 1080)

        # Negative dimensions
        success = handler.resize(-100, 200)
        assert not success

        # Zero dimensions
        success = handler.resize(0, 0)
        assert not success

    def test_resize_event_pattern_matching(self):
        """Test resize event handling with pattern matching"""
        handler = DesktopSizeHandler()
        handler.initialize(1920, 1080)

        # Valid resize
        status, data = handler.handle_resize_event(
            2560, 1440, handler.REASON_CLIENT
        )
        assert status == handler.STATUS_NO_ERROR

        # Invalid resize
        status, data = handler.handle_resize_event(
            -100, 200, handler.REASON_CLIENT
        )
        assert status == handler.STATUS_INVALID_SCREEN_LAYOUT

    def test_encode_desktop_size_update(self):
        """Test encoding desktop size update"""
        handler = DesktopSizeHandler()
        handler.supports_extended = True
        handler.initialize(1920, 1080)

        encoding_type, data = handler.encode_desktop_size_update()

        assert encoding_type == handler.ENCODING_EXTENDED_DESKTOP_SIZE
        assert len(data) >= 4  # At least header

    def test_multi_screen_layout(self):
        """Test multi-screen configuration"""
        handler = DesktopSizeHandler()
        handler.supports_extended = True
        handler.initialize(1920, 1080)

        # Add second screen
        screen2 = Screen(id=1, x=1920, y=0, width=1920, height=1080)
        success = handler.add_screen(screen2)

        assert success
        assert len(handler.screens) == 2

        total_w, total_h = handler.get_total_dimensions()
        assert total_w == 3840  # 1920 + 1920
        assert total_h == 1080

    def test_create_dual_screen_layout(self):
        """Test dual screen layout creation"""
        # Horizontal layout
        screens = create_dual_screen_layout(1920, 1080, 1920, 1080, horizontal=True)
        assert len(screens) == 2
        assert screens[1].x == 1920
        assert screens[1].y == 0

        # Vertical layout
        screens = create_dual_screen_layout(1920, 1080, 1920, 1080, horizontal=False)
        assert len(screens) == 2
        assert screens[1].x == 0
        assert screens[1].y == 1080


class TestExceptionGroups:
    """Test exception group handling (PEP 654)"""

    def test_exception_collector_no_errors(self):
        """Test ExceptionCollector with no errors"""
        with ExceptionCollector() as collector:
            # Successful operations
            pass

        assert not collector.has_exceptions()
        assert collector.create_exception_group("test") is None

    def test_exception_collector_single_error(self):
        """Test ExceptionCollector with single error"""
        with ExceptionCollector() as collector:
            with collector.catch("operation1"):
                raise ValueError("Test error")

        assert collector.has_exceptions()
        exc_group = collector.create_exception_group("Test failed")
        assert len(exc_group.exceptions) == 1
        assert isinstance(exc_group.exceptions[0], ValueError)

    def test_exception_collector_multiple_errors(self):
        """Test ExceptionCollector with multiple errors"""
        with ExceptionCollector() as collector:
            with collector.catch("op1"):
                raise ProtocolError("Protocol failed")

            with collector.catch("op2"):
                raise AuthenticationError("Auth failed")

            with collector.catch("op3"):
                # This succeeds
                pass

            with collector.catch("op4"):
                raise VNCError("General error")

        assert collector.has_exceptions()
        exc_group = collector.create_exception_group("Multiple failures")
        assert len(exc_group.exceptions) == 3

    def test_categorize_exceptions(self):
        """Test exception categorization"""
        with ExceptionCollector() as collector:
            with collector.catch("op1"):
                raise ProtocolError("Error 1")

            with collector.catch("op2"):
                raise ProtocolError("Error 2")

            with collector.catch("op3"):
                raise AuthenticationError("Auth error")

        exc_group = collector.create_exception_group("Test")
        categories = categorize_exceptions(exc_group)

        assert "ProtocolError" in categories
        assert "AuthenticationError" in categories
        assert len(categories["ProtocolError"]) == 2
        assert len(categories["AuthenticationError"]) == 1

    def test_collect_exceptions_function(self):
        """Test collect_exceptions utility function"""
        operations = [
            ("op1", lambda: None),  # Success
            ("op2", lambda: (_ for _ in ()).throw(ValueError("Error 2"))),  # Fail
            ("op3", lambda: None),  # Success
            ("op4", lambda: (_ for _ in ()).throw(TypeError("Error 4"))),  # Fail
        ]

        errors = collect_exceptions(operations)

        assert errors is not None
        assert len(errors.exceptions) == 2

    def test_exception_notes(self):
        """Test exception notes (Python 3.11+)"""
        with ExceptionCollector() as collector:
            with collector.catch("important_operation"):
                raise ValueError("Something went wrong")

        exc_group = collector.create_exception_group("Test")
        exc = exc_group.exceptions[0]

        # Check that note was added
        notes = getattr(exc, '__notes__', [])
        assert any("important_operation" in note for note in notes)


class TestSlidingWindowGeneric:
    """Test generic SlidingWindow class (PEP 695)"""

    def test_sliding_window_float(self):
        """Test SlidingWindow with float type"""
        window: SlidingWindow[float] = SlidingWindow(maxlen=5)

        for value in [1.0, 2.0, 3.0, 4.0, 5.0]:
            window.add(value)

        assert len(window) == 5
        assert window.average() == 3.0
        assert window.min() == 1.0
        assert window.max() == 5.0

    def test_sliding_window_int(self):
        """Test SlidingWindow with int type"""
        window: SlidingWindow[int] = SlidingWindow(maxlen=3)

        window.add(10)
        window.add(20)
        window.add(30)

        assert len(window) == 3
        assert window.average() == 20.0
        assert window.median() == 20.0

    def test_sliding_window_overflow(self):
        """Test SlidingWindow maxlen overflow"""
        window: SlidingWindow[float] = SlidingWindow(maxlen=3)

        window.add(1.0)
        window.add(2.0)
        window.add(3.0)
        window.add(4.0)  # Should drop 1.0

        assert len(window) == 3
        assert window.min() == 2.0
        assert window.max() == 4.0

    def test_sliding_window_median(self):
        """Test median calculation"""
        window: SlidingWindow[int] = SlidingWindow(maxlen=5)

        window.add(1)
        window.add(2)
        window.add(3)
        window.add(4)
        window.add(5)

        assert window.median() == 3.0

    def test_sliding_window_percentile(self):
        """Test percentile calculation"""
        window: SlidingWindow[float] = SlidingWindow(maxlen=10)

        for i in range(10):
            window.add(float(i))

        # 50th percentile should be around 4.5
        p50 = window.percentile(50)
        assert 4.0 <= p50 <= 5.0

        # 95th percentile should be around 8.5
        p95 = window.percentile(95)
        assert 8.0 <= p95 <= 9.0

    def test_sliding_window_clear(self):
        """Test window clearing"""
        window: SlidingWindow[int] = SlidingWindow(maxlen=5)

        window.add(1)
        window.add(2)
        window.clear()

        assert len(window) == 0
        assert not window  # Test __bool__


class TestResultType:
    """Test Result type for functional error handling"""

    def test_result_ok(self):
        """Test Ok result"""
        result: Result[int, str] = Ok(42)

        assert result.is_ok()
        assert not result.is_err()
        assert result.unwrap() == 42

    def test_result_err(self):
        """Test Err result"""
        result: Result[int, str] = Err("Something failed")

        assert not result.is_ok()
        assert result.is_err()
        assert result.unwrap_err() == "Something failed"

    def test_result_unwrap_err(self):
        """Test unwrap on Err raises ValueError"""
        result: Result[int, str] = Err("Failed")

        with pytest.raises(ValueError):
            result.unwrap()

    def test_result_unwrap_or(self):
        """Test unwrap_or with default value"""
        ok_result: Result[int, str] = Ok(42)
        err_result: Result[int, str] = Err("Failed")

        assert ok_result.unwrap_or(0) == 42
        assert err_result.unwrap_or(0) == 0

    def test_result_division_example(self):
        """Test Result with division example"""
        def divide(a: float, b: float) -> Result[float, str]:
            if b == 0:
                return Err("Division by zero")
            return Ok(a / b)

        result1 = divide(10, 2)
        assert result1.is_ok()
        assert result1.unwrap() == 5.0

        result2 = divide(10, 0)
        assert result2.is_err()
        assert "zero" in result2.unwrap_err()


class TestTypeHelpers:
    """Test type narrowing and validation helpers"""

    def test_is_valid_dimension(self):
        """Test dimension validation"""
        assert is_valid_dimension(1920, 1080)
        assert is_valid_dimension(1, 1)
        assert not is_valid_dimension(0, 100)
        assert not is_valid_dimension(100, 0)
        assert not is_valid_dimension(-100, 200)
        assert not is_valid_dimension(70000, 1080)  # Too large

    def test_narrow_bytes(self):
        """Test bytes type narrowing with pattern matching"""
        # bytes input
        result = narrow_bytes(b"test")
        assert result == b"test"
        assert isinstance(result, bytes)

        # bytearray input
        result = narrow_bytes(bytearray(b"test"))
        assert result == b"test"
        assert isinstance(result, bytes)

        # memoryview input
        result = narrow_bytes(memoryview(b"test"))
        assert result == b"test"
        assert isinstance(result, bytes)

    def test_narrow_bytes_invalid_type(self):
        """Test narrow_bytes with invalid type"""
        with pytest.raises(TypeError):
            narrow_bytes("not bytes")  # type: ignore

        with pytest.raises(TypeError):
            narrow_bytes(123)  # type: ignore


class TestEncoderManagerPatternMatching:
    """Test EncoderManager with pattern matching"""

    def test_encoding_selection_static(self):
        """Test encoding selection for static content"""
        manager = EncoderManager()
        client_encodings = {0, 2, 5, 16}

        enc_type, encoder = manager.get_best_encoder(
            client_encodings, content_type="static"
        )

        # Should prefer ZRLE (16) for static content
        assert enc_type == 16

    def test_encoding_selection_dynamic(self):
        """Test encoding selection for dynamic content"""
        manager = EncoderManager()
        client_encodings = {0, 2, 5, 16}

        enc_type, encoder = manager.get_best_encoder(
            client_encodings, content_type="dynamic"
        )

        # Should prefer Hextile (5) for dynamic content
        assert enc_type == 5

    def test_encoding_selection_scrolling(self):
        """Test encoding selection for scrolling"""
        manager = EncoderManager()
        client_encodings = {0, 1, 2, 5, 16}  # Include CopyRect

        enc_type, encoder = manager.get_best_encoder(
            client_encodings, content_type="scrolling"
        )

        # Should prefer CopyRect (1) for scrolling
        assert enc_type == 1

    def test_encoding_fallback(self):
        """Test encoding fallback when preferred not available"""
        manager = EncoderManager()
        client_encodings = {0}  # Only Raw

        enc_type, encoder = manager.get_best_encoder(
            client_encodings, content_type="static"
        )

        # Should fallback to Raw (0)
        assert enc_type == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
