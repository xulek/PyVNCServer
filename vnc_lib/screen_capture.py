"""
Screen Capture Module
Handles screen grabbing and pixel format conversion
Enhanced with Python 3.13 features and high-performance mss backend
"""

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
        self._cached_bgra_bytes: bytes | None = None
        self._cached_width: int = 0
        self._cached_height: int = 0
        self._cache_time: float = 0.0
        self._cache_ttl: float = 0.016  # ~60 FPS max

        # Buffer pre-allocation for performance (avoid repeated allocations)
        self._rgb_buffer: bytearray | None = None
        self._pixel_buffer: bytearray | None = None
        self._buffer_size: int = 0
        self._palette_lut_cache: dict[tuple[int, int, int, int, int, int], tuple[bytes, bytes, bytes]] = {}
        self._numpy_lut_cache: dict[tuple[int, int, int, int, int, int], tuple] = {}

        # Try to load numpy (fast 8bpp conversion)
        self._numpy_available = False
        self._np = None
        self._lazy_load_numpy()

    def _lazy_load_numpy(self):
        """Lazy load numpy module (fast 8bpp vectorized conversion)"""
        if not self._numpy_available:
            try:
                import numpy
                self._np = numpy
                self._numpy_available = True
            except ImportError as e:
                self.logger.debug(f"numpy not available, 8bpp conversion will use pure Python: {e}")
                self._numpy_available = False

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

    def _is_bgr0_format(self, pixel_format: dict) -> bool:
        """Check if client wants BGR0 format (matches native BGRA capture output)"""
        return (
            pixel_format.get('bits_per_pixel') == 32
            and pixel_format.get('depth') == 24
            and pixel_format.get('true_colour_flag', 0)
            and not pixel_format.get('big_endian_flag', 0)
            and pixel_format.get('red_shift') == 16
            and pixel_format.get('green_shift') == 8
            and pixel_format.get('blue_shift') == 0
        )

    def _is_rgb0_format(self, pixel_format: dict) -> bool:
        """Check if client wants RGB0 format"""
        return (
            pixel_format.get('bits_per_pixel') == 32
            and pixel_format.get('depth') == 24
            and pixel_format.get('true_colour_flag', 0)
            and not pixel_format.get('big_endian_flag', 0)
            and pixel_format.get('red_shift') == 0
            and pixel_format.get('green_shift') == 8
            and pixel_format.get('blue_shift') == 16
        )

    def _grab_screen_bgra(self) -> tuple[bytes | None, int, int]:
        """
        Grab screenshot as raw BGRA bytes (no color conversion).
        Only available with mss backend.

        Returns:
            (bgra_bytes, width, height) or (None, 0, 0) on error
        """
        current_time = time.time()

        if (self._cached_bgra_bytes is not None and
            current_time - self._cache_time < self._cache_ttl):
            return self._cached_bgra_bytes, self._cached_width, self._cached_height

        if not self._mss_available:
            return None, 0, 0

        try:
            monitor = self._sct.monitors[self.monitor] if self.monitor < len(self._sct.monitors) else self._sct.monitors[0]
            sct_img = self._sct.grab(monitor)
            width = sct_img.width
            height = sct_img.height
            bgra_bytes = bytes(sct_img.raw)

            self._cached_bgra_bytes = bgra_bytes
            self._cached_rgb_bytes = None  # Invalidate RGB cache
            self._cached_width = width
            self._cached_height = height
            self._cache_time = current_time

            return bgra_bytes, width, height
        except Exception as e:
            self.logger.error(f"Failed to grab screen (BGRA): {e}")
            return None, 0, 0

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

            # Fast path: for 32-bit formats with mss, work directly with BGRA
            # to avoid the expensive intermediate RGB conversion
            if self._mss_available and self.scale_factor == 1.0:
                bgra_bytes, width, height = self._grab_screen_bgra()
                if bgra_bytes is not None:
                    num_pixels = width * height
                    pixel_data = self._convert_bgra_to_pixel_format(
                        bgra_bytes, width, height, num_pixels, pixel_format
                    )
                    if pixel_data is not None:
                        elapsed = time.perf_counter() - start_time
                        self.logger.debug(
                            f"Screen capture (BGRA fast path): {width}x{height}, "
                            f"{len(pixel_data)} bytes, {elapsed*1000:.2f}ms"
                        )
                        return CaptureResult(pixel_data, None, width, height, elapsed)

            # Standard path: grab as RGB, then convert
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

            elapsed = time.perf_counter() - start_time
            self.logger.debug(
                f"Screen capture: {width}x{height}, "
                f"{len(pixel_data)} bytes, {elapsed*1000:.2f}ms"
            )

            return CaptureResult(pixel_data, None, width, height, elapsed)

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
            self._cached_bgra_bytes = None  # Invalidate BGRA cache
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

    def _convert_bgra_to_pixel_format(self, bgra_bytes: bytes, width: int, height: int,
                                      num_pixels: int, pixel_format: dict) -> bytes | None:
        """
        Convert BGRA bytes directly to VNC pixel format, skipping intermediate RGB.
        Returns None if the format isn't a 32-bit true color format we can handle.

        Benchmark results show BGRA->RGB0 swap costs ~50ms at 1080p.
        For BGR0 format (red_shift=16, blue_shift=0), we can skip the swap entirely.
        """
        bpp = pixel_format.get('bits_per_pixel', 0)
        if not pixel_format.get('true_colour_flag', 0):
            return None  # Fall back to standard path

        big_endian = pixel_format.get('big_endian_flag', 0)
        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']

        # Fast path for 8-bit true color (e.g. RGB222/RGB332) directly from BGRA.
        # This avoids BGRA->RGB conversion and significantly reduces startup cost
        # for clients that temporarily switch to low color depth.
        if bpp == 8 and not big_endian:
            red_max = pixel_format.get('red_max', 0)
            green_max = pixel_format.get('green_max', 0)
            blue_max = pixel_format.get('blue_max', 0)
            if red_max <= 0 or green_max <= 0 or blue_max <= 0:
                return None

            lut_key = (red_shift, green_shift, blue_shift, red_max, green_max, blue_max)
            luts = self._palette_lut_cache.get(lut_key)
            if luts is None:
                r_lut = bytes((((v * red_max) // 255) << red_shift & 0xFF) for v in range(256))
                g_lut = bytes((((v * green_max) // 255) << green_shift & 0xFF) for v in range(256))
                b_lut = bytes((((v * blue_max) // 255) << blue_shift & 0xFF) for v in range(256))
                luts = (r_lut, g_lut, b_lut)
                self._palette_lut_cache[lut_key] = luts
            r_lut, g_lut, b_lut = luts

            # Numpy fast path: vectorized LUT indexing (~5ms vs ~838ms pure Python)
            if self._numpy_available:
                np = self._np
                np_luts = self._numpy_lut_cache.get(lut_key)
                if np_luts is None:
                    r_lut_np = np.frombuffer(r_lut, dtype=np.uint8)
                    g_lut_np = np.frombuffer(g_lut, dtype=np.uint8)
                    b_lut_np = np.frombuffer(b_lut, dtype=np.uint8)
                    np_luts = (r_lut_np, g_lut_np, b_lut_np)
                    self._numpy_lut_cache[lut_key] = np_luts
                r_lut_np, g_lut_np, b_lut_np = np_luts
                arr = np.frombuffer(bgra_bytes, dtype=np.uint8).reshape(-1, 4)
                result = r_lut_np[arr[:, 2]] | g_lut_np[arr[:, 1]] | b_lut_np[arr[:, 0]]
                return result.tobytes()

            # Pure-Python fallback for when numpy is not available
            if self._pixel_buffer is None or len(self._pixel_buffer) != num_pixels:
                self._pixel_buffer = bytearray(num_pixels)
            out = self._pixel_buffer
            src = memoryview(bgra_bytes)
            out_idx = 0
            for i in range(0, num_pixels * 4, 4):
                out[out_idx] = (
                    r_lut[src[i + 2]]
                    | g_lut[src[i + 1]]
                    | b_lut[src[i + 0]]
                )
                out_idx += 1
            return bytes(out)

        if bpp != 32:
            return None  # Fall back to standard path

        pixel_size = num_pixels * 4
        if self._pixel_buffer is None or len(self._pixel_buffer) != pixel_size:
            self._pixel_buffer = bytearray(pixel_size)

        bgra_view = memoryview(bgra_bytes)
        pix_view = memoryview(self._pixel_buffer)

        if not big_endian and red_shift == 16 and green_shift == 8 and blue_shift == 0:
            # BGR0: native BGRA capture is B(0) G(8) R(16) A(24)
            # The client expects B(0) G(8) R(16) with padding byte — identical layout!
            # Use the BGRA data directly; the alpha byte (pos 3) becomes padding.
            # True zero-copy: no channel swapping or memoryview copying needed.
            return bgra_bytes

        if not big_endian and red_shift == 0 and green_shift == 8 and blue_shift == 16:
            # RGB0: swap B and R channels from BGRA
            pix_view[0::4] = bgra_view[2::4]  # R (from BGRA pos 2)
            pix_view[1::4] = bgra_view[1::4]  # G
            pix_view[2::4] = bgra_view[0::4]  # B (from BGRA pos 0)
            return bytes(self._pixel_buffer)

        # Other 32-bit formats: fall back to standard path
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
