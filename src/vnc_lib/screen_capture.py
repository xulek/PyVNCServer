"""
Screen Capture Module
Handles screen grabbing and pixel format conversion
Enhanced with Python 3.13 features and high-performance mss backend
"""

import logging
import os
import struct
import time
import threading
from typing import NamedTuple, TYPE_CHECKING, Any
import statistics

from .capture_backends import (
    BaseCaptureBackend,
    CaptureFrame,
    CaptureMetadata,
    DXCamCaptureBackend,
    MSSCaptureBackend,
    PILCaptureBackend,
)

if TYPE_CHECKING:
    from PIL import ImageGrab, Image
    import dxcam
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

    def __init__(self, scale_factor: float = 1.0, monitor: int = 0,
                 backend_preference: str = "auto"):
        """
        Initialize screen capture

        Args:
            scale_factor: Scale factor for resizing (1.0 = no scaling)
            monitor: Monitor index for multi-monitor setups (0 = all monitors)
        """
        self.scale_factor = scale_factor
        self.monitor = monitor
        self.backend_preference = str(backend_preference).strip().lower() or "auto"
        self.logger = logging.getLogger(__name__)
        self.last_checksum: bytes | None = None
        self._capture_lock = threading.RLock()
        self._thread_local = threading.local()
        self._active_backend = "none"
        self._backend: BaseCaptureBackend | None = None
        self._backend_registry: dict[str, BaseCaptureBackend] = {}

        # Try to load dxcam (DXGI Desktop Duplication backend)
        self._dxcam_available = False
        self._dxcam = None
        self._lazy_load_dxcam()

        # Try to load mss (high performance backend)
        self._mss_available = False
        self._mss = None
        self._lazy_load_mss()

        # Fallback: Lazy load PIL (only when needed)
        self._pil_available = False
        self._ImageGrab = None
        self._Image = None
        if not self._mss_available:
            self._lazy_load_pil()

        self._build_backend_registry()
        self._apply_backend_preference()

        # Log which backend is being used
        if self._active_backend == "dxcam":
            self.logger.info("Using dxcam backend for DXGI desktop duplication capture")
        elif self._active_backend == "mss":
            self.logger.info("Using mss backend for high-performance screen capture")
        elif self._active_backend == "pil":
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

    def _lazy_load_dxcam(self):
        """Lazy load dxcam module (Windows DXGI Desktop Duplication backend)."""
        if self._dxcam_available or os.name != "nt":
            return
        try:
            import dxcam
            self._dxcam = dxcam
            self._dxcam_available = True
        except ImportError as e:
            self.logger.debug(f"dxcam not available: {e}")
            self._dxcam_available = False

    def _lazy_load_mss(self):
        """Lazy load mss module (high-performance backend)"""
        if not self._mss_available:
            try:
                import mss
                self._mss = mss
                self._mss_available = True
            except ImportError as e:
                self.logger.debug(f"mss not available: {e}")
                self._mss_available = False

    def _get_mss_session(self):
        """
        Get an mss session bound to the current thread.

        MSS keeps backend state in thread-local storage on Windows, so a
        session created in one thread cannot be safely reused from another.
        """
        if not self._mss_available or self._mss is None:
            return None

        session = getattr(self._thread_local, 'sct', None)
        if session is None:
            session = self._mss.mss()
            self._thread_local.sct = session
        return session

    def _get_dxcam_session(self):
        """Get a dxcam camera bound to the current thread."""
        if not self._dxcam_available or self._dxcam is None:
            return None

        camera = getattr(self._thread_local, "dxcam_camera", None)
        if camera is not None:
            return camera

        create = getattr(self._dxcam, "create", None)
        if create is None:
            return None

        output_idx = self.monitor if self.monitor > 0 else 0
        attempts = (
            ("BGRA", {"output_color": "BGRA"}),
            ("BGR", {"output_color": "BGR"}),
            ("RGB", {"output_color": "RGB"}),
        )
        for color_hint, kwargs in attempts:
            try:
                camera = create(output_idx=output_idx, **kwargs)
                self._thread_local.dxcam_camera = camera
                self._thread_local.dxcam_color_hint = color_hint
                return camera
            except TypeError:
                continue
            except Exception as e:
                self.logger.debug("dxcam create(%s) failed: %s", color_hint, e)

        try:
            camera = create(output_idx=output_idx)
            self._thread_local.dxcam_camera = camera
            self._thread_local.dxcam_color_hint = "unknown"
            return camera
        except Exception as e:
            self.logger.warning("Failed to initialize dxcam backend: %s", e)
            return None

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

    def _build_backend_registry(self):
        """Build backend adapters once imports/availability probes are ready."""
        self._backend_registry = {
            "dxcam": DXCamCaptureBackend(self),
            "mss": MSSCaptureBackend(self),
            "pil": PILCaptureBackend(self),
        }

    def _apply_backend_preference(self):
        """Honor explicit backend preference without hiding fallback behavior."""
        if self.backend_preference not in {"auto", "dxcam", "mss", "pil"}:
            self.logger.warning(
                "Unknown capture backend preference '%s'; using auto",
                self.backend_preference,
            )
            self.backend_preference = "auto"

        if self.backend_preference == "dxcam":
            if self._backend_registry["dxcam"].is_available():
                self._set_active_backend("dxcam")
            else:
                self.logger.warning("capture_backend='dxcam' requested, but dxcam is unavailable")

        if self.backend_preference == "mss":
            if self._backend_registry["mss"].is_available():
                self._set_active_backend("mss")
            else:
                self.logger.warning("capture_backend='mss' requested, but mss is unavailable")
            return

        if self.backend_preference == "pil":
            if not self._pil_available:
                self._lazy_load_pil()
            if self._backend_registry["pil"].is_available():
                self._set_active_backend("pil")
            else:
                self.logger.warning("capture_backend='pil' requested, but Pillow is unavailable")
            return

        if self._active_backend == "dxcam":
            return

        if self.backend_preference == "mss":
            return

        if self.backend_preference == "pil":
            return

        if self._backend_registry["mss"].is_available():
            self._set_active_backend("mss")
        elif self._backend_registry["pil"].is_available():
            self._set_active_backend("pil")
        else:
            self._active_backend = "none"
            self._backend = None

    def _set_active_backend(self, backend_name: str):
        """Assign the active backend adapter."""
        self._active_backend = backend_name
        self._backend = self._backend_registry.get(backend_name)

    def get_backend_name(self) -> str:
        """Return the currently active capture backend name."""
        return self._active_backend

    def get_backend_capabilities(self) -> CaptureMetadata:
        """Expose backend metadata capabilities in a stable shape."""
        if self._backend is None:
            return CaptureMetadata(backend_name="none")
        return self._backend.build_metadata(0, 0)

    def capture_frame(self, pixel_format: dict) -> CaptureFrame:
        """Capture a frame together with backend metadata hints."""
        result = self.capture_fast(pixel_format)
        metadata = (
            self._backend.build_metadata(result.width, result.height)
            if self._backend is not None
            else CaptureMetadata(backend_name="none")
        )
        return CaptureFrame(result=result, metadata=metadata)

    def benchmark_capture(self, pixel_format: dict, iterations: int = 10,
                          warmup: int = 2) -> dict[str, float | int | str]:
        """
        Measure actual capture_fast latency for the active backend.

        The benchmark temporarily disables cache reuse so it reflects real capture cost.
        """
        iterations = max(1, int(iterations))
        warmup = max(0, int(warmup))

        previous_ttl = self._cache_ttl
        self._cache_ttl = 0.0
        try:
            for _ in range(warmup):
                self.capture_fast(pixel_format)

            samples_ms: list[float] = []
            width = 0
            height = 0
            bytes_out = 0
            for _ in range(iterations):
                result = self.capture_fast(pixel_format)
                if result.pixel_data is None:
                    continue
                samples_ms.append(result.capture_time * 1000.0)
                width = result.width
                height = result.height
                bytes_out = len(result.pixel_data)

            if not samples_ms:
                return {
                    "backend": self.get_backend_name(),
                    "iterations": 0,
                    "avg_ms": 0.0,
                    "min_ms": 0.0,
                    "max_ms": 0.0,
                    "fps": 0.0,
                    "width": width,
                    "height": height,
                    "bytes": bytes_out,
                }

            avg_ms = statistics.mean(samples_ms)
            return {
                "backend": self.get_backend_name(),
                "iterations": len(samples_ms),
                "avg_ms": avg_ms,
                "min_ms": min(samples_ms),
                "max_ms": max(samples_ms),
                "fps": 1000.0 / avg_ms if avg_ms > 0 else 0.0,
                "width": width,
                "height": height,
                "bytes": bytes_out,
            }
        finally:
            self._cache_ttl = previous_ttl

    def _ensure_capture_backend(self):
        """Ensure at least one capture backend is available"""
        if self._active_backend == "none":
            raise RuntimeError(
                "No screen capture backend available. Please install mss or Pillow:\n"
                "pip install dxcam  # Optional Windows DXGI backend\n"
                "pip install mss  # Recommended: high-performance\n"
                "pip install Pillow  # Alternative: fallback backend\n"
            )

    def _ensure_pil(self):
        """Ensure PIL backend is available for region capture/scaling helpers."""
        if not self._pil_available:
            self._lazy_load_pil()
        if not self._pil_available or self._ImageGrab is None or self._Image is None:
            raise RuntimeError(
                "Pillow is required for this screen capture operation. "
                "Install it with: pip install Pillow"
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
        Available with dxcam and mss backends.

        Returns:
            (bgra_bytes, width, height) or (None, 0, 0) on error
        """
        current_time = time.time()

        if (self._cached_bgra_bytes is not None and
            current_time - self._cache_time < self._cache_ttl):
            return self._cached_bgra_bytes, self._cached_width, self._cached_height

        try:
            if self._backend is None or not self._backend.capabilities.supports_bgra:
                return None, 0, 0
            bgra_bytes, width, height = self._backend.grab_bgra()
            if bgra_bytes is None:
                return None, 0, 0

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
        with self._capture_lock:
            try:
                self._ensure_capture_backend()
                start_time = time.perf_counter()

            # Fast path: for 32-bit formats with mss, work directly with BGRA
            # to avoid the expensive intermediate RGB conversion
                if self._active_backend in {"dxcam", "mss"} and self.scale_factor == 1.0:
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
            if self._backend is None:
                return None, 0, 0
            rgb_bytes, width, height = self._backend.grab_rgb()
            if rgb_bytes is None:
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
            if self._backend is not None and self._backend.capabilities.supports_pil_image:
                screenshot = self._backend.grab_image()
                if screenshot is not None:
                    self._cached_screenshot = screenshot
                    self._cache_time = current_time
                    return screenshot
            elif self._active_backend in {"dxcam", "mss"}:
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

    def _grab_dxcam_frame(self) -> tuple[bytes | None, int, int, int, str]:
        """Grab a raw frame from dxcam if available."""
        current_time = time.time()
        if (
            self._cached_bgra_bytes is not None
            and current_time - self._cache_time < self._cache_ttl
            and self._active_backend == "dxcam"
        ):
            return (
                self._cached_bgra_bytes,
                self._cached_width,
                self._cached_height,
                4,
                "BGRA",
            )

        camera = self._get_dxcam_session()
        if camera is None:
            return None, 0, 0, 0, "unknown"

        try:
            frame = camera.grab()
            if frame is None or not hasattr(frame, "shape"):
                return None, 0, 0, 0, "unknown"

            shape = getattr(frame, "shape", ())
            if len(shape) < 2:
                return None, 0, 0, 0, "unknown"

            height = int(shape[0])
            width = int(shape[1])
            channels = int(shape[2]) if len(shape) >= 3 else 1
            color_hint = getattr(self._thread_local, "dxcam_color_hint", "unknown")
            frame_bytes = frame.tobytes() if hasattr(frame, "tobytes") else bytes(frame)
            return frame_bytes, width, height, channels, color_hint
        except Exception as e:
            self.logger.error("Failed to grab screen (dxcam): %s", e)
            return None, 0, 0, 0, "unknown"

    def _dxcam_frame_to_bgra(
        self,
        frame_bytes: bytes,
        width: int,
        height: int,
        channels: int,
        color_hint: str,
    ) -> bytes | None:
        """Convert a dxcam frame into BGRA bytes."""
        num_pixels = width * height

        if channels == 4 and color_hint == "BGRA":
            return frame_bytes

        out = bytearray(num_pixels * 4)
        if channels == 3 and color_hint == "BGR":
            src = memoryview(frame_bytes)
            dst = memoryview(out)
            dst[0::4] = src[0::3]
            dst[1::4] = src[1::3]
            dst[2::4] = src[2::3]
            dst[3::4] = b"\x00" * num_pixels
            return bytes(out)

        if channels == 3 and color_hint == "RGB":
            src = memoryview(frame_bytes)
            dst = memoryview(out)
            dst[0::4] = src[2::3]
            dst[1::4] = src[1::3]
            dst[2::4] = src[0::3]
            dst[3::4] = b"\x00" * num_pixels
            return bytes(out)

        return None

    def _dxcam_frame_to_rgb(
        self,
        frame_bytes: bytes,
        width: int,
        height: int,
        channels: int,
        color_hint: str,
    ) -> bytes | None:
        """Convert a dxcam frame into RGB bytes."""
        num_pixels = width * height
        out = bytearray(num_pixels * 3)
        src = memoryview(frame_bytes)
        dst = memoryview(out)

        if channels == 4 and color_hint == "BGRA":
            dst[0::3] = src[2::4]
            dst[1::3] = src[1::4]
            dst[2::3] = src[0::4]
            return bytes(out)

        if channels == 3 and color_hint == "BGR":
            dst[0::3] = src[2::3]
            dst[1::3] = src[1::3]
            dst[2::3] = src[0::3]
            return bytes(out)

        if channels == 3 and color_hint == "RGB":
            return frame_bytes

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
        with self._capture_lock:
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
