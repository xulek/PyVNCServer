"""
JPEG Encoding Implementation for VNC
Provides lossy compression for photographic/video content
Encoding Type: 21 (Tight JPEG sub-encoding)
"""

import struct
import logging
from typing import TypeAlias
from io import BytesIO

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL not available - JPEG encoding disabled")

# Type aliases
PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes


class JPEGEncoder:
    """
    JPEG Encoding for VNC (Type 21 - Tight JPEG sub-encoding)

    Uses JPEG compression for photographic content and video.
    Provides excellent compression (50-200x) but is lossy.

    Best for:
    - Video playback
    - Photos and images
    - Complex graphics with many colors

    Not good for:
    - Text (artifacts)
    - UI elements (blurry)
    - Line art
    """

    ENCODING_TYPE = 21  # Tight JPEG Quality Level pseudo-encoding
    JPEG_ENCODING_TYPE = 7  # Uses Tight encoding with JPEG sub-encoding

    # JPEG quality levels
    QUALITY_MIN = 1
    QUALITY_MAX = 100
    QUALITY_DEFAULT = 80  # Good balance between size and quality

    # JPEG is only efficient for larger rectangles
    MIN_JPEG_SIZE = 4096  # Minimum pixels to consider JPEG

    def __init__(self, quality: int = QUALITY_DEFAULT):
        """
        Initialize JPEG encoder

        Args:
            quality: JPEG quality level (1-100)
                    1 = smallest file, worst quality
                    100 = largest file, best quality
                    80 = recommended default
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL (Pillow) is required for JPEG encoding. "
                             "Install with: pip install Pillow")

        self.quality = max(self.QUALITY_MIN, min(self.QUALITY_MAX, quality))
        self.logger = logging.getLogger(__name__)

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        Encode pixel data as JPEG

        Args:
            pixel_data: Raw pixel data
            width: Image width
            height: Image height
            bytes_per_pixel: Bytes per pixel (3 or 4)

        Returns:
            Encoded JPEG data with Tight encoding header
        """
        # JPEG only makes sense for larger images
        if width * height < self.MIN_JPEG_SIZE:
            self.logger.debug(f"JPEG: image too small ({width}x{height}), "
                             "not using JPEG")
            return pixel_data  # Return raw data, let Tight handle it

        if bytes_per_pixel not in (3, 4):
            self.logger.warning(f"JPEG: unsupported bpp {bytes_per_pixel}")
            return pixel_data

        try:
            # Convert pixel data to PIL Image
            mode = "RGB" if bytes_per_pixel == 3 else "RGBA"
            image = Image.frombytes(mode, (width, height), pixel_data)

            # Convert 4bpp to RGB (strip padding byte — our data is BGR0/RGB0, not true RGBA)
            if mode == "RGBA":
                image = image.convert("RGB")

            # Encode as JPEG
            jpeg_buffer = BytesIO()
            image.save(jpeg_buffer, format="JPEG", quality=self.quality,
                      optimize=False, progressive=False)
            jpeg_data = jpeg_buffer.getvalue()

            # Build Tight encoding format with JPEG sub-encoding
            # Control byte: 0x90 = JPEG compression (rfbTightJpeg << 4)
            control = 0x90
            result = bytearray([control])

            # Add compact length
            result.extend(self._encode_compact_length(len(jpeg_data)))

            # Add JPEG data
            result.extend(jpeg_data)

            compression_ratio = len(pixel_data) / len(result)
            self.logger.debug(f"JPEG: {len(pixel_data)} -> {len(result)} bytes "
                             f"({compression_ratio:.1f}x compression, quality={self.quality})")

            return bytes(result)

        except Exception as e:
            self.logger.error(f"JPEG encoding failed: {e}")
            return pixel_data  # Fallback to raw

    def encode_rectangle(self, pixel_data: PixelData, x: int, y: int,
                        width: int, height: int, bytes_per_pixel: int) -> tuple:
        """
        Encode rectangle for VNC framebuffer update

        Returns: (x, y, width, height, encoding_type, encoded_data)
        """
        encoded = self.encode(pixel_data, width, height, bytes_per_pixel)
        return (x, y, width, height, self.JPEG_ENCODING_TYPE, encoded)

    def _encode_compact_length(self, length: int) -> bytes:
        """
        Encode length in Tight's compact format

        Format:
        - If length <= 127: 1 byte
        - If length <= 16383: 2 bytes (bits 0-6 of first byte, bit 7 = 1)
        - Otherwise: 3 bytes
        """
        if length <= 127:
            return bytes([length])
        elif length <= 16383:
            return bytes([0x80 | (length & 0x7F), (length >> 7) & 0xFF])
        else:
            return bytes([0x80 | (length & 0x7F),
                         0x80 | ((length >> 7) & 0x7F),
                         (length >> 14) & 0xFF])

    def set_quality(self, quality: int):
        """Update JPEG quality level"""
        new_quality = max(self.QUALITY_MIN, min(self.QUALITY_MAX, quality))
        if new_quality != self.quality:
            self.quality = new_quality
            self.logger.debug(f"JPEG quality set to {self.quality}")

    def is_suitable_for_jpeg(self, pixel_data: PixelData, width: int,
                            height: int, bytes_per_pixel: int) -> bool:
        """
        Check if content is suitable for JPEG compression

        JPEG works best for:
        - Large images (> 4096 pixels)
        - Photographic content
        - Video frames
        - Complex color gradients

        JPEG is bad for:
        - Small images
        - Text
        - UI elements
        - Simple graphics
        """
        # Size check
        if width * height < self.MIN_JPEG_SIZE:
            return False

        # Check color complexity (JPEG good for many colors)
        num_unique_colors = self._count_unique_colors(pixel_data, bytes_per_pixel,
                                                       sample_size=1000)

        # If many colors (> 256), likely photographic - good for JPEG
        if num_unique_colors > 256:
            return True

        # Check for gradients (JPEG good for smooth gradients)
        if self._has_gradients(pixel_data, width, height, bytes_per_pixel):
            return True

        return False

    def _count_unique_colors(self, pixel_data: PixelData, bpp: int,
                            sample_size: int = 1000) -> int:
        """
        Count unique colors in image (sampled for speed)

        Args:
            pixel_data: Raw pixel data
            bpp: Bytes per pixel
            sample_size: Number of pixels to sample

        Returns:
            Estimated number of unique colors
        """
        unique_colors: set[bytes] = set()
        step = max(1, len(pixel_data) // (sample_size * bpp))

        for i in range(0, len(pixel_data), step * bpp):
            if len(unique_colors) > 256:
                break  # Already know it's complex
            pixel = pixel_data[i:i+bpp]
            unique_colors.add(pixel)

        return len(unique_colors)

    def _has_gradients(self, pixel_data: PixelData, width: int,
                      height: int, bpp: int) -> bool:
        """Check if image has smooth gradients (sample-based)"""
        if width < 4 or height < 4:
            return False

        # Sample a few rows for gradient detection
        smooth_transitions = 0
        total_samples = 0

        for y in range(0, min(height, 20), 4):
            for x in range(1, min(width, 20), 4):
                offset = (y * width + x) * bpp
                prev_offset = (y * width + x - 1) * bpp

                if offset + bpp <= len(pixel_data):
                    current = pixel_data[offset:offset+bpp]
                    previous = pixel_data[prev_offset:prev_offset+bpp]

                    # Check if colors are similar (gradient)
                    diff = sum(abs(a - b) for a, b in zip(current, previous))
                    if diff < 30:  # Small difference = smooth gradient
                        smooth_transitions += 1

                    total_samples += 1

        return total_samples > 0 and smooth_transitions / total_samples > 0.4


class AdaptiveJPEGEncoder(JPEGEncoder):
    """
    Adaptive JPEG encoder that adjusts quality based on content

    Automatically adjusts JPEG quality based on:
    - Content complexity
    - Desired compression ratio
    - Bandwidth constraints
    """

    def __init__(self, target_compression: float = 50.0,
                 min_quality: int = 50, max_quality: int = 95):
        """
        Initialize adaptive JPEG encoder

        Args:
            target_compression: Target compression ratio (e.g., 50x)
            min_quality: Minimum JPEG quality (when bandwidth is constrained)
            max_quality: Maximum JPEG quality (when bandwidth is good)
        """
        super().__init__(quality=max_quality)
        self.target_compression = target_compression
        self.min_quality = min_quality
        self.max_quality = max_quality
        self.current_quality = max_quality

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """Encode with adaptive quality"""
        # Use current adaptive quality
        old_quality = self.quality
        self.quality = self.current_quality

        result = super().encode(pixel_data, width, height, bytes_per_pixel)

        # Restore quality
        self.quality = old_quality

        return result

    def adjust_quality(self, actual_compression: float):
        """
        Adjust quality based on actual compression ratio

        If compression is too low, reduce quality
        If compression is higher than needed, increase quality
        """
        if actual_compression < self.target_compression * 0.8:
            # Not compressing enough - reduce quality
            self.current_quality = max(self.min_quality,
                                      self.current_quality - 5)
            self.logger.debug(f"Reducing JPEG quality to {self.current_quality} "
                            f"(compression: {actual_compression:.1f}x)")
        elif actual_compression > self.target_compression * 1.2:
            # Compressing too much - increase quality
            self.current_quality = min(self.max_quality,
                                      self.current_quality + 5)
            self.logger.debug(f"Increasing JPEG quality to {self.current_quality} "
                            f"(compression: {actual_compression:.1f}x)")
