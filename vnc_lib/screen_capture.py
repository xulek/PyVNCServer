"""
Screen Capture Module
Handles screen grabbing and pixel format conversion
Enhanced with Python 3.13 features
"""

import hashlib
import logging
import struct
import time
from typing import NamedTuple, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import ImageGrab, Image


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

        # Lazy load PIL (only when needed)
        self._pil_available = False
        self._ImageGrab = None
        self._Image = None
        self._lazy_load_pil()

        # Performance optimization: cache last screenshot
        self._cached_screenshot: Any = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 0.016  # ~60 FPS max

    def _lazy_load_pil(self):
        """Lazy load PIL modules"""
        if not self._pil_available:
            try:
                from PIL import ImageGrab, Image
                self._ImageGrab = ImageGrab
                self._Image = Image
                self._pil_available = True
            except ImportError as e:
                self.logger.warning(f"PIL not available: {e}")
                self._pil_available = False

    def _ensure_pil(self):
        """Ensure PIL is available, raise error if not"""
        if not self._pil_available:
            raise RuntimeError(
                "PIL (Pillow) is not available. Please install it:\n"
                "pip install Pillow\n"
                "ScreenCapture requires PIL/Pillow to function."
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
            self._ensure_pil()
            start_time = time.perf_counter()

            # Grab screenshot
            screenshot = self._grab_screen()
            if screenshot is None:
                return CaptureResult(None, None, 0, 0, 0.0)

            width, height = screenshot.size

            # Apply scaling if needed
            if self.scale_factor != 1.0:
                scaled_width = int(width * self.scale_factor)
                scaled_height = int(height * self.scale_factor)

                if scaled_width < 1 or scaled_height < 1:
                    self.logger.warning("Scale factor too small")
                    return CaptureResult(None, None, 0, 0, 0.0)

                screenshot = screenshot.resize(
                    (scaled_width, scaled_height),
                    self._Image.Resampling.BILINEAR
                )
                width, height = scaled_width, scaled_height

            # Convert to requested pixel format
            pixel_data = self._convert_to_pixel_format(screenshot, pixel_format)

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

    def _grab_screen(self) -> Any:
        """
        Grab screenshot with caching for performance

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
            screenshot = self._ImageGrab.grab(all_screens=(self.monitor == 0))
            self._cached_screenshot = screenshot
            self._cache_time = current_time
            return screenshot
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

    def _convert_to_pixel_format(self, image: Any, pixel_format: dict) -> bytes:
        """
        Convert image to client's requested pixel format

        Supports various pixel formats as per RFC 6143 Section 7.4
        """
        bpp = pixel_format['bits_per_pixel']
        depth = pixel_format['depth']
        true_colour = pixel_format['true_colour_flag']
        big_endian = pixel_format['big_endian_flag']

        if true_colour and bpp == 32 and depth == 24:
            # 32-bit true color (most common)
            return self._convert_to_32bit_true_color(image, pixel_format, big_endian)
        elif true_colour and bpp == 16:
            # 16-bit true color
            return self._convert_to_16bit_true_color(image, pixel_format, big_endian)
        elif true_colour and bpp == 8:
            # 8-bit true color
            return self._convert_to_8bit_true_color(image, pixel_format)
        else:
            # Default fallback: 32-bit RGBA
            self.logger.warning(f"Unsupported pixel format (bpp={bpp}, depth={depth}, "
                              f"true_colour={true_colour}), using 32-bit RGBA")
            return image.convert("RGBA").tobytes()

    def _convert_to_32bit_true_color(self, image: Any,
                                     pixel_format: dict, big_endian: bool) -> bytes:
        """Convert to 32-bit true color format - ULTRA OPTIMIZED VERSION"""
        # Get RGB data as bytes (MUCH faster than pixel-by-pixel access)
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        rgb_bytes = rgb_image.tobytes()  # Fast: R,G,B,R,G,B,R,G,B,...

        # Extract shift values
        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']

        num_pixels = width * height

        # Ultra fast path for standard RGB0 format (most common)
        if not big_endian and red_shift == 0 and green_shift == 8 and blue_shift == 16:
            # Standard RGB0 format - use array slicing (ultra fast)
            data = bytearray(num_pixels * 4)
            # Use slicing to copy RGB channels efficiently
            data[0::4] = rgb_bytes[0::3]  # R channel
            data[1::4] = rgb_bytes[1::3]  # G channel
            data[2::4] = rgb_bytes[2::3]  # B channel
            # data[3::4] already initialized to 0 (padding)
            return bytes(data)

        # Ultra fast path for BGR0 format
        elif not big_endian and red_shift == 16 and green_shift == 8 and blue_shift == 0:
            # Standard BGR0 format - use array slicing (ultra fast)
            data = bytearray(num_pixels * 4)
            # Use slicing to copy BGR channels efficiently
            data[0::4] = rgb_bytes[2::3]  # B channel (from R in source)
            data[1::4] = rgb_bytes[1::3]  # G channel
            data[2::4] = rgb_bytes[0::3]  # R channel (from B in source)
            # data[3::4] already initialized to 0 (padding)
            return bytes(data)

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

    def _convert_to_16bit_true_color(self, image: Any,
                                     pixel_format: dict, big_endian: bool) -> bytes:
        """Convert to 16-bit true color format (e.g., RGB565) - OPTIMIZED VERSION"""
        # Get RGB data as bytes (MUCH faster than pixel-by-pixel access)
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        rgb_bytes = rgb_image.tobytes()  # Fast: R,G,B,R,G,B,R,G,B,...

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

    def _convert_to_8bit_true_color(self, image: Any, pixel_format: dict) -> bytes:
        """Convert to 8-bit true color format (e.g., RGB332) - OPTIMIZED VERSION"""
        # Get RGB data as bytes (MUCH faster than pixel-by-pixel access)
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        rgb_bytes = rgb_image.tobytes()  # Fast: R,G,B,R,G,B,R,G,B,...

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

    def has_changed(self, checksum: bytes) -> bool:
        """Check if screen has changed since last capture"""
        if self.last_checksum is None:
            return True
        return checksum != self.last_checksum

    def update_checksum(self, checksum: bytes):
        """Update last checksum"""
        self.last_checksum = checksum
