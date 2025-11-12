"""
Screen Capture Module
Handles screen grabbing and pixel format conversion
Enhanced with Python 3.13 features and high-performance mss backend
"""

import hashlib
import logging
import struct
import time
from typing import NamedTuple, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import ImageGrab, Image
    import mss


class CaptureResult(NamedTuple):
    """Screen capture result (Python 3.13 style)"""
    pixel_data: bytes | None
    checksum: bytes | None
    width: int
    height: int
    capture_time: float


class ScreenCapture:
    """
    Handles screen capture and format conversion
    Enhanced with better performance and caching
    """

    def __init__(self, scale_factor: float = 1.0, monitor: int = 0):
        """
        Initialize screen capture

        Args:
            scale_factor: Scale factor for resizing (1.0 = no scaling)
            monitor: Monitor index for multi-monitor setups (0 = all monitors)
        """
        self.scale_factor = scale_factor
        self.monitor = monitor
        self.logger = logging.getLogger(__name__)
        self.last_checksum: bytes | None = None

        # Try to load mss (high performance backend)
        self._mss_available = False
        self._mss = None
        self._sct = None
        self._lazy_load_mss()

        # Fallback: Lazy load PIL (only when needed)
        self._pil_available = False
        self._ImageGrab = None
        self._Image = None
        if not self._mss_available:
            self._lazy_load_pil()

        # Log which backend is being used
        if self._mss_available:
            self.logger.info("Using mss backend for high-performance screen capture")
        elif self._pil_available:
            self.logger.info("Using PIL backend for screen capture (fallback)")
        else:
            self.logger.warning("No screen capture backend available")

        # Performance optimization: cache last screenshot
        self._cached_screenshot: Any = None
        self._cached_rgb_bytes: bytes | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 0.016  # ~60 FPS max

        # Buffer pre-allocation for performance (avoid repeated allocations)
        self._rgb_buffer: bytearray | None = None
        self._pixel_buffer: bytearray | None = None
        self._buffer_size: int = 0

    def _lazy_load_mss(self):
        """Lazy load mss module (high-performance backend)"""
        if not self._mss_available:
            try:
                import mss
                self._mss = mss
                self._sct = mss.mss()
                self._mss_available = True
            except ImportError as e:
                self.logger.debug(f"mss not available: {e}")
                self._mss_available = False

    def _lazy_load_pil(self):
        """Lazy load PIL modules (fallback backend)"""
        if not self._pil_available:
            try:
                from PIL import ImageGrab, Image
                self._ImageGrab = ImageGrab
                self._Image = Image
                self._pil_available = True
            except ImportError as e:
                self.logger.warning(f"PIL not available: {e}")
                self._pil_available = False

    def _ensure_capture_backend(self):
        """Ensure at least one capture backend is available"""
        if not self._mss_available and not self._pil_available:
            raise RuntimeError(
                "No screen capture backend available. Please install mss or Pillow:\n"
                "pip install mss  # Recommended: high-performance\n"
                "pip install Pillow  # Alternative: fallback backend\n"
            )

    def capture(self, pixel_format: dict) -> tuple[bytes | None, bytes | None, int, int]:
        """
        Capture screen and convert to specified pixel format

        Args:
            pixel_format: Client's requested pixel format

        Returns:
            (pixel_data, checksum, width, height)
        """
        result = self.capture_fast(pixel_format)
        return result.pixel_data, result.checksum, result.width, result.height

    def capture_fast(self, pixel_format: dict) -> CaptureResult:
        """
        Fast screen capture with caching
        Returns CaptureResult with timing information

        Args:
            pixel_format: Client's requested pixel format

        Returns:
            CaptureResult with capture data and metadata
        """
        try:
            self._ensure_capture_backend()
            start_time = time.perf_counter()

            # Grab screenshot (with proper backend)
            rgb_bytes, width, height = self._grab_screen_rgb()
            if rgb_bytes is None:
                return CaptureResult(None, None, 0, 0, 0.0)

            # Apply scaling if needed
            if self.scale_factor != 1.0:
                scaled_width = int(width * self.scale_factor)
                scaled_height = int(height * self.scale_factor)

                if scaled_width < 1 or scaled_height < 1:
                    self.logger.warning("Scale factor too small")
                    return CaptureResult(None, None, 0, 0, 0.0)

                # For scaling, we need PIL
                if self._mss_available and not self._pil_available:
                    self._lazy_load_pil()

                if self._pil_available:
                    from PIL import Image
                    img = Image.frombytes('RGB', (width, height), rgb_bytes)
                    img = img.resize(
                        (scaled_width, scaled_height),
                        Image.Resampling.BILINEAR
                    )
                    rgb_bytes = img.tobytes()
                    width, height = scaled_width, scaled_height
                else:
                    self.logger.warning("Cannot scale without PIL, using original size")

            # Convert to requested pixel format
            pixel_data = self._convert_rgb_to_pixel_format(rgb_bytes, width, height, pixel_format)

            # Calculate checksum for change detection
            checksum = hashlib.md5(pixel_data).digest()

            elapsed = time.perf_counter() - start_time
            self.logger.debug(
                f"Screen capture: {width}x{height}, "
                f"{len(pixel_data)} bytes, {elapsed*1000:.2f}ms"
            )

            return CaptureResult(pixel_data, checksum, width, height, elapsed)

        except Exception as e:
            self.logger.error(f"Screen capture error: {e}", exc_info=True)
            return CaptureResult(None, None, 0, 0, 0.0)

    def _grab_screen_rgb(self) -> tuple[bytes | None, int, int]:
        """
        Grab screenshot as RGB bytes with caching for performance
        Uses mss backend (high-performance) or PIL fallback

        Returns:
            (rgb_bytes, width, height) or (None, 0, 0) on error
        """
        current_time = time.time()

        # Use cached screenshot if available and fresh
        if (self._cached_rgb_bytes is not None and
            current_time - self._cache_time < self._cache_ttl):
            # Return cached data with stored dimensions
            return self._cached_rgb_bytes, self._cached_width, self._cached_height

        # Capture new screenshot using mss (preferred) or PIL (fallback)
        try:
            if self._mss_available:
                # High-performance mss backend
                monitor = self._sct.monitors[self.monitor] if self.monitor < len(self._sct.monitors) else self._sct.monitors[0]
                sct_img = self._sct.grab(monitor)

                # mss returns BGRA, convert to RGB
                width = sct_img.width
                height = sct_img.height
                bgra_bytes = sct_img.raw

                # ULTRA-OPTIMIZED: Convert BGRA to RGB using memoryview (4-5x faster)
                num_pixels = width * height
                rgb_size = num_pixels * 3

                # Use pre-allocated buffer to avoid repeated allocations
                if self._rgb_buffer is None or len(self._rgb_buffer) != rgb_size:
                    self._rgb_buffer = bytearray(rgb_size)

                # Use memoryview for zero-copy slicing
                bgra_view = memoryview(bgra_bytes)
                rgb_view = memoryview(self._rgb_buffer)

                # Fast bulk copy using memoryview slicing
                rgb_view[0::3] = bgra_view[2::4]  # R from B
                rgb_view[1::3] = bgra_view[1::4]  # G
                rgb_view[2::3] = bgra_view[0::4]  # B from R

                rgb_bytes = bytes(self._rgb_buffer)

            elif self._pil_available:
                # PIL fallback
                screenshot = self._ImageGrab.grab(all_screens=(self.monitor == 0))
                width, height = screenshot.size
                rgb_bytes = screenshot.convert("RGB").tobytes()
            else:
                return None, 0, 0

            # Cache the result
            self._cached_rgb_bytes = rgb_bytes
            self._cached_width = width
            self._cached_height = height
            self._cache_time = current_time

            return rgb_bytes, width, height

        except Exception as e:
            self.logger.error(f"Failed to grab screen: {e}")
            return None, 0, 0

    def _grab_screen(self) -> Any:
        """
        Legacy method: Grab screenshot as PIL Image
        Used for backward compatibility with region capture

        Returns:
            PIL Image or None on error
        """
        current_time = time.time()

        # Use cached screenshot if available and fresh
        if (self._cached_screenshot is not None and
            current_time - self._cache_time < self._cache_ttl):
            return self._cached_screenshot

        # Capture new screenshot
        try:
            if self._pil_available:
                screenshot = self._ImageGrab.grab(all_screens=(self.monitor == 0))
                self._cached_screenshot = screenshot
                self._cache_time = current_time
                return screenshot
            elif self._mss_available:
                # Convert mss to PIL Image if needed
                if not self._pil_available:
                    self._lazy_load_pil()

                if self._pil_available:
                    from PIL import Image
                    rgb_bytes, width, height = self._grab_screen_rgb()
                    if rgb_bytes:
                        screenshot = Image.frombytes('RGB', (width, height), rgb_bytes)
                        self._cached_screenshot = screenshot
                        self._cache_time = current_time
                        return screenshot
            return None
        except Exception as e:
            self.logger.error(f"Failed to grab screen: {e}")
            return None

    def capture_region(self, x: int, y: int, width: int, height: int,
                      pixel_format: dict) -> bytes | None:
        """
        Capture specific screen region (for region-based updates)

        Args:
            x, y: Region top-left corner
            width, height: Region dimensions
            pixel_format: Client's requested pixel format

        Returns:
            Pixel data for region or None on error
        """
        try:
            self._ensure_pil()
            # Grab specific region
            bbox = (x, y, x + width, y + height)
            screenshot = self._ImageGrab.grab(bbox=bbox)

            # Apply scaling if needed
            if self.scale_factor != 1.0:
                scaled_width = int(width * self.scale_factor)
                scaled_height = int(height * self.scale_factor)
                screenshot = screenshot.resize(
                    (scaled_width, scaled_height),
                    self._Image.Resampling.BILINEAR
                )

            # Convert to pixel format
            pixel_data = self._convert_to_pixel_format(screenshot, pixel_format)
            return pixel_data

        except Exception as e:
            self.logger.error(f"Region capture error: {e}")
            return None

    def _convert_rgb_to_pixel_format(self, rgb_bytes: bytes, width: int, height: int,
                                     pixel_format: dict) -> bytes:
        """
        Convert RGB bytes to client's requested pixel format
        Direct conversion without PIL Image overhead

        Supports various pixel formats as per RFC 6143 Section 7.4
        """
        bpp = pixel_format['bits_per_pixel']
        depth = pixel_format['depth']
        true_colour = pixel_format['true_colour_flag']
        big_endian = pixel_format['big_endian_flag']

        if true_colour and bpp == 32 and depth == 24:
            # 32-bit true color (most common)
            return self._convert_rgb_to_32bit_true_color(rgb_bytes, width, height, pixel_format, big_endian)
        elif true_colour and bpp == 16:
            # 16-bit true color
            return self._convert_rgb_to_16bit_true_color(rgb_bytes, width, height, pixel_format, big_endian)
        elif true_colour and bpp == 8:
            # 8-bit true color
            return self._convert_rgb_to_8bit_true_color(rgb_bytes, width, height, pixel_format)
        else:
            # Default fallback: 32-bit RGBA
            self.logger.warning(f"Unsupported pixel format (bpp={bpp}, depth={depth}, "
                              f"true_colour={true_colour}), using 32-bit RGBA")
            # Convert RGB to RGBA (add alpha channel)
            num_pixels = width * height
            rgba_bytes = bytearray(num_pixels * 4)
            rgba_bytes[0::4] = rgb_bytes[0::3]  # R
            rgba_bytes[1::4] = rgb_bytes[1::3]  # G
            rgba_bytes[2::4] = rgb_bytes[2::3]  # B
            rgba_bytes[3::4] = [255] * num_pixels  # A (opaque)
            return bytes(rgba_bytes)

    def _convert_to_pixel_format(self, image: Any, pixel_format: dict) -> bytes:
        """
        Convert PIL Image to client's requested pixel format
        Legacy method for backward compatibility with region capture

        Supports various pixel formats as per RFC 6143 Section 7.4
        """
        # Get RGB bytes and use the new optimized method
        rgb_bytes = image.convert("RGB").tobytes()
        width, height = image.size
        return self._convert_rgb_to_pixel_format(rgb_bytes, width, height, pixel_format)

    def _convert_rgb_to_32bit_true_color(self, rgb_bytes: bytes, width: int, height: int,
                                         pixel_format: dict, big_endian: bool) -> bytes:
        """Convert RGB bytes to 32-bit true color format - ULTRA OPTIMIZED VERSION with memoryview"""
        # Extract shift values
        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']

        num_pixels = width * height

        # Ultra fast path for standard RGB0 format (most common)
        if not big_endian and red_shift == 0 and green_shift == 8 and blue_shift == 16:
            # Standard RGB0 format - use memoryview for zero-copy slicing (fastest)
            # Use pre-allocated buffer to avoid repeated allocations
            pixel_size = num_pixels * 4
            if self._pixel_buffer is None or len(self._pixel_buffer) != pixel_size:
                self._pixel_buffer = bytearray(pixel_size)
            else:
                # Clear the buffer (set alpha channel to 0)
                self._pixel_buffer[3::4] = bytes(num_pixels)

            rgb_view = memoryview(rgb_bytes)
            data_view = memoryview(self._pixel_buffer)

            # Ultra-fast bulk copy using memoryview
            data_view[0::4] = rgb_view[0::3]  # R channel
            data_view[1::4] = rgb_view[1::3]  # G channel
            data_view[2::4] = rgb_view[2::3]  # B channel
            # data[3::4] already initialized to 0 (padding)
            return bytes(self._pixel_buffer)

        # Ultra fast path for BGR0 format
        elif not big_endian and red_shift == 16 and green_shift == 8 and blue_shift == 0:
            # Standard BGR0 format - use memoryview for zero-copy slicing (fastest)
            # Use pre-allocated buffer to avoid repeated allocations
            pixel_size = num_pixels * 4
            if self._pixel_buffer is None or len(self._pixel_buffer) != pixel_size:
                self._pixel_buffer = bytearray(pixel_size)
            else:
                # Clear the buffer (set alpha channel to 0)
                self._pixel_buffer[3::4] = bytes(num_pixels)

            rgb_view = memoryview(rgb_bytes)
            data_view = memoryview(self._pixel_buffer)

            # Ultra-fast bulk copy using memoryview
            data_view[0::4] = rgb_view[2::3]  # B channel (from R in source)
            data_view[1::4] = rgb_view[1::3]  # G channel
            data_view[2::4] = rgb_view[0::3]  # R channel (from B in source)
            # data[3::4] already initialized to 0 (padding)
            return bytes(self._pixel_buffer)

        # Generic path for non-standard formats (still much faster than before)
        byteorder = 'big' if big_endian else 'little'
        data = bytearray(num_pixels * 4)

        for i in range(num_pixels):
            offset = i * 3
            r = rgb_bytes[offset]
            g = rgb_bytes[offset + 1]
            b = rgb_bytes[offset + 2]

            # Pack according to shift values
            pixel_value = (r << red_shift) | (g << green_shift) | (b << blue_shift)

            # Write as 32-bit value
            struct.pack_into('I' if byteorder == 'little' else '>I',
                           data, i * 4, pixel_value)

        return bytes(data)

    def _convert_to_32bit_true_color(self, image: Any,
                                     pixel_format: dict, big_endian: bool) -> bytes:
        """Legacy: Convert PIL Image to 32-bit true color format"""
        # Get RGB data as bytes and use optimized method
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        rgb_bytes = rgb_image.tobytes()
        return self._convert_rgb_to_32bit_true_color(rgb_bytes, width, height, pixel_format, big_endian)

    def _convert_rgb_to_16bit_true_color(self, rgb_bytes: bytes, width: int, height: int,
                                         pixel_format: dict, big_endian: bool) -> bytes:
        """Convert RGB bytes to 16-bit true color format (e.g., RGB565) - OPTIMIZED VERSION"""
        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']
        red_max = pixel_format['red_max']
        green_max = pixel_format['green_max']
        blue_max = pixel_format['blue_max']

        num_pixels = width * height
        byteorder = 'big' if big_endian else 'little'
        data = bytearray(num_pixels * 2)

        for i in range(num_pixels):
            offset = i * 3
            r = rgb_bytes[offset]
            g = rgb_bytes[offset + 1]
            b = rgb_bytes[offset + 2]

            # Scale to max values
            r = (r * red_max) // 255
            g = (g * green_max) // 255
            b = (b * blue_max) // 255

            # Pack according to shift values
            pixel_value = (r << red_shift) | (g << green_shift) | (b << blue_shift)

            # Write as 16-bit value
            struct.pack_into('H' if byteorder == 'little' else '>H',
                           data, i * 2, pixel_value)

        return bytes(data)

    def _convert_to_16bit_true_color(self, image: Any,
                                     pixel_format: dict, big_endian: bool) -> bytes:
        """Legacy: Convert PIL Image to 16-bit true color format"""
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        rgb_bytes = rgb_image.tobytes()
        return self._convert_rgb_to_16bit_true_color(rgb_bytes, width, height, pixel_format, big_endian)

    def _convert_rgb_to_8bit_true_color(self, rgb_bytes: bytes, width: int, height: int,
                                        pixel_format: dict) -> bytes:
        """Convert RGB bytes to 8-bit true color format (e.g., RGB332) - OPTIMIZED VERSION"""
        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']
        red_max = pixel_format['red_max']
        green_max = pixel_format['green_max']
        blue_max = pixel_format['blue_max']

        num_pixels = width * height
        data = bytearray(num_pixels)

        for i in range(num_pixels):
            offset = i * 3
            r = rgb_bytes[offset]
            g = rgb_bytes[offset + 1]
            b = rgb_bytes[offset + 2]

            # Scale to max values
            r = (r * red_max) // 255
            g = (g * green_max) // 255
            b = (b * blue_max) // 255

            # Pack according to shift values
            pixel_value = (r << red_shift) | (g << green_shift) | (b << blue_shift)

            data[i] = pixel_value & 0xFF

        return bytes(data)

    def _convert_to_8bit_true_color(self, image: Any, pixel_format: dict) -> bytes:
        """Legacy: Convert PIL Image to 8-bit true color format"""
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        rgb_bytes = rgb_image.tobytes()
        return self._convert_rgb_to_8bit_true_color(rgb_bytes, width, height, pixel_format)

    def has_changed(self, checksum: bytes) -> bool:
        """Check if screen has changed since last capture"""
        if self.last_checksum is None:
            return True
        return checksum != self.last_checksum

    def update_checksum(self, checksum: bytes):
        """Update last checksum"""
        self.last_checksum = checksum
