"""
VNC Encoding Implementations
Supports various RFB encodings for efficient data transmission
"""

import struct
import zlib
import logging
from typing import Protocol, TypeAlias
from collections.abc import Callable


# Type aliases (Python 3.12+ would use 'type' statement)
PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes
Rectangle: TypeAlias = tuple[int, int, int, int]  # x, y, width, height


class Encoder(Protocol):
    """Protocol for encoder implementations (Python 3.13 style)"""

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """Encode pixel data"""
        ...


class RawEncoder:
    """Raw encoding - uncompressed pixel data (RFC 6143 Section 7.7.1)"""

    ENCODING_TYPE = 0

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """Raw encoding simply returns the pixel data as-is"""
        return pixel_data


class CopyRectEncoder:
    """
    CopyRect encoding - RFC 6143 Section 7.6.2
    Efficiently copies a rectangle from one screen position to another
    Perfect for scrolling, window movement, and drag operations

    Note: CopyRect data is just (src_x, src_y) - 4 bytes total
    The client copies the rectangle from (src_x, src_y) to the target position
    """

    ENCODING_TYPE = 1

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.previous_frame: PixelData | None = None
        self.frame_width: int = 0
        self.frame_height: int = 0

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        CopyRect encoding - finds matching rectangles from previous frame

        Returns: struct.pack(">HH", src_x, src_y) if match found, else pixel_data
        """
        # Store current frame for next comparison
        if self.previous_frame is None or width != self.frame_width or height != self.frame_height:
            self.previous_frame = pixel_data
            self.frame_width = width
            self.frame_height = height
            # First frame - no copy possible
            return pixel_data

        # Try to find matching rectangle in previous frame
        match = self._find_matching_region(
            pixel_data, self.previous_frame, width, height, bytes_per_pixel
        )

        # Update previous frame
        self.previous_frame = pixel_data

        if match:
            src_x, src_y = match
            self.logger.debug(f"CopyRect: source ({src_x}, {src_y})")
            return struct.pack(">HH", src_x, src_y)

        # No match found, fallback to raw
        return pixel_data

    def _find_matching_region(self, current: PixelData, previous: PixelData,
                              width: int, height: int, bpp: int,
                              min_match_size: int = 64) -> tuple[int, int] | None:
        """
        Find matching region in previous frame

        Returns: (src_x, src_y) if match found with sufficient size
        """
        # Simple implementation: check if entire image shifted
        # A full implementation would check multiple regions

        # Check for vertical scroll (most common case)
        for dy in [-10, -5, -3, -2, -1, 1, 2, 3, 5, 10]:
            if self._is_vertical_shift(current, previous, width, height, bpp, dy):
                # Determine source position based on shift direction
                src_y = max(0, -dy) if dy < 0 else 0
                return (0, src_y)

        # Check for horizontal scroll
        for dx in [-10, -5, -3, -2, -1, 1, 2, 3, 5, 10]:
            if self._is_horizontal_shift(current, previous, width, height, bpp, dx):
                src_x = max(0, -dx) if dx < 0 else 0
                return (src_x, 0)

        return None

    def _is_vertical_shift(self, current: PixelData, previous: PixelData,
                          width: int, height: int, bpp: int, dy: int) -> bool:
        """Check if image shifted vertically by dy pixels"""
        if abs(dy) >= height:
            return False

        # Check if lines match after shift
        matches = 0
        check_lines = min(10, height - abs(dy))  # Check 10 lines

        for y in range(check_lines):
            curr_y = y if dy > 0 else y + abs(dy)
            prev_y = y + dy if dy > 0 else y

            if 0 <= curr_y < height and 0 <= prev_y < height:
                curr_offset = curr_y * width * bpp
                prev_offset = prev_y * width * bpp
                line_size = width * bpp

                if current[curr_offset:curr_offset + line_size] == previous[prev_offset:prev_offset + line_size]:
                    matches += 1

        return matches >= check_lines * 0.8  # 80% match threshold

    def _is_horizontal_shift(self, current: PixelData, previous: PixelData,
                            width: int, height: int, bpp: int, dx: int) -> bool:
        """Check if image shifted horizontally by dx pixels"""
        if abs(dx) >= width:
            return False

        # Check if columns match after shift (sample-based)
        matches = 0
        check_cols = min(10, width - abs(dx))

        for x in range(check_cols):
            curr_x = x if dx > 0 else x + abs(dx)
            prev_x = x + dx if dx > 0 else x

            if 0 <= curr_x < width and 0 <= prev_x < width:
                # Check a few pixels in this column
                match_count = 0
                for y in range(0, height, max(1, height // 10)):
                    curr_offset = (y * width + curr_x) * bpp
                    prev_offset = (y * width + prev_x) * bpp

                    if current[curr_offset:curr_offset + bpp] == previous[prev_offset:prev_offset + bpp]:
                        match_count += 1

                if match_count >= 8:  # At least 8/10 pixels match
                    matches += 1

        return matches >= check_cols * 0.8  # 80% match threshold


class RREEncoder:
    """
    RRE (Rise-and-Run-length Encoding) - RFC 6143 Section 7.6.4
    Efficient for images with large solid-color rectangles
    """

    ENCODING_TYPE = 2
    DEFAULT_MAX_PIXELS = 256 * 256
    DEFAULT_MAX_SUBRECTANGLES = 4096
    DEFAULT_BACKGROUND_SAMPLE_PIXELS = 65536

    def __init__(self, max_pixels: int = DEFAULT_MAX_PIXELS,
                 max_subrectangles: int = DEFAULT_MAX_SUBRECTANGLES,
                 background_sample_pixels: int = DEFAULT_BACKGROUND_SAMPLE_PIXELS):
        self.logger = logging.getLogger(__name__)
        self.max_pixels = max(1, int(max_pixels))
        self.max_subrectangles = max(1, int(max_subrectangles))
        self.background_sample_pixels = max(256, int(background_sample_pixels))

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        RRE encoding format:
        - 4 bytes: number of subrectangles
        - background pixel value (bytes_per_pixel)
        - for each subrectangle:
            - pixel value (bytes_per_pixel)
            - x, y, width, height (2 bytes each)
        """
        if bytes_per_pixel not in (1, 2, 4):
            self.logger.warning(f"RRE: unsupported bpp {bytes_per_pixel}")
            return pixel_data

        num_pixels = width * height
        if num_pixels <= 0:
            return pixel_data
        if len(pixel_data) < num_pixels * bytes_per_pixel:
            self.logger.warning("RRE: pixel buffer smaller than expected, falling back to raw")
            return pixel_data
        if num_pixels > self.max_pixels:
            self.logger.debug(
                f"RRE: region too large ({num_pixels} px > {self.max_pixels}), using raw"
            )
            return pixel_data

        # Find background color (most common pixel)
        background = self._find_background(pixel_data, bytes_per_pixel)

        # Find rectangles of different colors
        subrects = self._find_subrectangles(
            pixel_data, width, height, bytes_per_pixel, background,
            max_subrectangles=self.max_subrectangles
        )
        if subrects is None:
            self.logger.debug("RRE: too many subrectangles, using raw")
            return pixel_data

        # Build encoded data
        result = bytearray()
        result.extend(struct.pack(">I", len(subrects)))  # Number of subrectangles
        result.extend(background)  # Background pixel value

        for pixel_value, x, y, w, h in subrects:
            result.extend(pixel_value)
            result.extend(struct.pack(">HHHH", x, y, w, h))

        # Only use RRE if it's more efficient
        if len(result) < len(pixel_data):
            self.logger.debug(f"RRE: {len(pixel_data)} -> {len(result)} bytes")
            return bytes(result)
        else:
            # Fallback to raw if RRE doesn't help
            return pixel_data

    def _find_background(self, pixel_data: PixelData, bpp: int) -> bytes:
        """Find most common pixel value (background)"""
        pixel_counts: dict[bytes, int] = {}
        num_pixels = len(pixel_data) // bpp
        sample_stride = 1
        if num_pixels > self.background_sample_pixels:
            sample_stride = max(1, num_pixels // self.background_sample_pixels)
        step = bpp * sample_stride

        for i in range(0, len(pixel_data), step):
            pixel = pixel_data[i:i+bpp]
            pixel_counts[pixel] = pixel_counts.get(pixel, 0) + 1

        # Return most common pixel
        return max(pixel_counts.items(), key=lambda x: x[1])[0] if pixel_counts else pixel_data[:bpp]

    def _find_subrectangles(self, pixel_data: PixelData, width: int,
                           height: int, bpp: int,
                           background: bytes,
                           max_subrectangles: int) -> list[tuple[bytes, int, int, int, int]] | None:
        """Find rectangles of non-background colors"""
        subrects: list[tuple[bytes, int, int, int, int]] = []
        processed = [[False] * width for _ in range(height)]

        for y in range(height):
            for x in range(width):
                if processed[y][x]:
                    continue

                offset = (y * width + x) * bpp
                pixel = pixel_data[offset:offset+bpp]

                if pixel == background:
                    processed[y][x] = True
                    continue

                # Find rectangle of same color starting at (x, y)
                rect_width = 1
                rect_height = 1

                # Expand horizontally
                while x + rect_width < width:
                    offset = (y * width + x + rect_width) * bpp
                    if pixel_data[offset:offset+bpp] != pixel or processed[y][x + rect_width]:
                        break
                    rect_width += 1

                # Expand vertically
                can_expand = True
                while can_expand and y + rect_height < height:
                    for dx in range(rect_width):
                        offset = ((y + rect_height) * width + x + dx) * bpp
                        if (pixel_data[offset:offset+bpp] != pixel or
                            processed[y + rect_height][x + dx]):
                            can_expand = False
                            break
                    if can_expand:
                        rect_height += 1

                # Mark as processed
                for dy in range(rect_height):
                    for dx in range(rect_width):
                        processed[y + dy][x + dx] = True

                subrects.append((pixel, x, y, rect_width, rect_height))
                if len(subrects) > max_subrectangles:
                    return None

        return subrects


class HextileEncoder:
    """
    Hextile encoding - RFC 6143 Section 7.6.5
    Divides framebuffer into 16x16 tiles
    """

    ENCODING_TYPE = 5
    TILE_SIZE = 16

    # Subencoding bits
    RAW = 0x01
    BACKGROUND_SPECIFIED = 0x02
    FOREGROUND_SPECIFIED = 0x04
    ANY_SUBRECTS = 0x08
    SUBRECTS_COLOURED = 0x10

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        Hextile encoding divides the framebuffer into 16x16 tiles
        and encodes each tile independently
        """
        result = bytearray()

        for tile_y in range(0, height, self.TILE_SIZE):
            for tile_x in range(0, width, self.TILE_SIZE):
                tile_width = min(self.TILE_SIZE, width - tile_x)
                tile_height = min(self.TILE_SIZE, height - tile_y)

                tile_data = self._extract_tile(
                    pixel_data, width, tile_x, tile_y,
                    tile_width, tile_height, bytes_per_pixel
                )

                encoded_tile = self._encode_tile(
                    tile_data, tile_width, tile_height, bytes_per_pixel
                )
                result.extend(encoded_tile)

        return bytes(result)

    def _extract_tile(self, pixel_data: PixelData, fb_width: int,
                     tile_x: int, tile_y: int, tile_width: int,
                     tile_height: int, bpp: int) -> PixelData:
        """Extract a tile from the framebuffer"""
        tile = bytearray()

        for y in range(tile_height):
            offset = ((tile_y + y) * fb_width + tile_x) * bpp
            tile.extend(pixel_data[offset:offset + tile_width * bpp])

        return bytes(tile)

    def _encode_tile(self, tile_data: PixelData, width: int,
                    height: int, bpp: int) -> EncodedData:
        """Encode a single tile"""
        # For simplicity, use raw encoding for tiles
        # A full implementation would analyze the tile and choose
        # the most efficient subencoding
        subencoding = self.RAW

        result = bytearray()
        result.append(subencoding)
        result.extend(tile_data)

        return bytes(result)


class ZlibEncoder:
    """
    Zlib encoding (type 6, non-standard but widely supported extension).

    Rectangle payload format:
    - 4-byte big-endian length
    - zlib-compressed raw pixel bytes
    """

    ENCODING_TYPE = 6

    def __init__(self, compression_level: int = 1):
        self.compression_level = max(1, min(9, int(compression_level)))
        self._compressor = zlib.compressobj(level=self.compression_level)
        self.logger = logging.getLogger(__name__)

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        if pixel_data is None:
            pixel_data = b''

        # Keep one zlib stream per client/encoder instance as expected by
        # the Zlib encoding extension. Sync flush preserves stream state
        # while framing each rectangle independently.
        compressed = (
            self._compressor.compress(pixel_data)
            + self._compressor.flush(zlib.Z_SYNC_FLUSH)
        )
        result = struct.pack(">I", len(compressed)) + compressed
        self.logger.debug(
            f"Zlib: {len(pixel_data)} -> {len(compressed)} bytes (level={self.compression_level})"
        )
        return result

    def set_compression_level(self, level: int):
        """Update compression level and reset stream state safely."""
        new_level = max(1, min(9, int(level)))
        if new_level != self.compression_level:
            self.compression_level = new_level
            self._compressor = zlib.compressobj(level=self.compression_level)


class ZRLEEncoder:
    """
    ZRLE (Zlib Run-Length Encoding) - RFC 6143 Section 7.6.6
    Combines run-length encoding with zlib compression
    """

    ENCODING_TYPE = 16

    def __init__(self, compression_level: int = 6):
        """
        Initialize ZRLE encoder

        Args:
            compression_level: zlib compression level (1-9)
        """
        self.compression_level = compression_level
        self._compressor = zlib.compressobj(level=self.compression_level)
        self.logger = logging.getLogger(__name__)

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        ZRLE encoding:
        1. Encode pixel data using run-length encoding
        2. Compress with zlib
        3. Prepend length header
        """
        if not pixel_data:
            compressed = (
                self._compressor.compress(b'')
                + self._compressor.flush(zlib.Z_SYNC_FLUSH)
            )
            return struct.pack(">I", len(compressed)) + compressed

        # Convert to CPIXEL format (compact pixel format)
        cpixel_data, cpixel_bpp = self._convert_to_cpixel(pixel_data, bytes_per_pixel)

        # Apply run-length encoding
        rle_data = self._apply_rle(cpixel_data, cpixel_bpp)

        # Compress with persistent zlib stream (warm dictionary improves ratio)
        compressed = (
            self._compressor.compress(rle_data)
            + self._compressor.flush(zlib.Z_SYNC_FLUSH)
        )

        # Prepend length (4 bytes, big-endian)
        result = struct.pack(">I", len(compressed)) + compressed

        self.logger.debug(
            f"ZRLE: {len(pixel_data)} -> {len(rle_data)} -> {len(compressed)} bytes"
        )

        return result

    def _convert_to_cpixel(self, pixel_data: PixelData, bpp: int) -> tuple[bytes, int]:
        """
        Convert to CPIXEL format
        For 32-bit pixels, use 3 bytes (RGB) instead of 4 (RGBA)
        """
        if bpp in (1, 2, 3):
            return pixel_data, bpp

        if bpp == 4:
            # Keep channel ordering, only drop padding byte.
            num_pixels = len(pixel_data) // 4
            result = bytearray(num_pixels * 3)
            src_view = memoryview(pixel_data)
            dst_view = memoryview(result)
            dst_view[0::3] = src_view[0::4]
            dst_view[1::3] = src_view[1::4]
            dst_view[2::3] = src_view[2::4]
            return bytes(result), 3

        self.logger.warning(f"ZRLE: unsupported bpp {bpp}, treating as single-byte pixels")
        return pixel_data, 1

    def _apply_rle(self, pixel_data: PixelData, pixel_size: int) -> bytes:
        """
        Apply run-length encoding

        ZRLE uses a tile-based approach (64x64 tiles)
        For simplicity, this implementation works on the whole image
        """
        if pixel_size <= 0:
            return b''
        if not pixel_data:
            return b''
        if len(pixel_data) < pixel_size:
            return b''

        if len(pixel_data) % pixel_size != 0:
            # Keep decoder state valid even for malformed buffers.
            usable_len = len(pixel_data) - (len(pixel_data) % pixel_size)
            pixel_data = pixel_data[:usable_len]
            if not pixel_data:
                return b''

        result = bytearray()

        i = 0
        while i < len(pixel_data):
            pixel = pixel_data[i:i+pixel_size]
            run_length = 1

            # Count consecutive identical pixels
            while (i + run_length * pixel_size < len(pixel_data) and
                   pixel_data[i+run_length*pixel_size:i+(run_length+1)*pixel_size] == pixel):
                run_length += 1
                if run_length >= 255:  # Max run length
                    break

            if run_length > 1:
                # Encoded as: pixel value + run length
                result.extend(pixel)
                result.append(run_length)
            else:
                # Single pixel
                result.extend(pixel)
                result.append(1)

            i += run_length * pixel_size

        return bytes(result)


class EncoderManager:
    """
    Manages encoding selection based on client preferences
    and content analysis (Python 3.13 style)
    """

    def __init__(self, enable_tight: bool = True, enable_h264: bool = False,
                 enable_jpeg: bool = True, disable_tight_for_ultravnc: bool = True):
        self.encoders: dict[int, Encoder] = {
            0: RawEncoder(),
            1: CopyRectEncoder(),  # CopyRect for scrolling/movement
            2: RREEncoder(),
            5: HextileEncoder(),
            6: ZlibEncoder(),
            16: ZRLEEncoder(),
        }

        # Add advanced encoders if enabled
        if enable_tight:
            try:
                from vnc_lib.tight_encoding import TightEncoder
                self.encoders[7] = TightEncoder()
                self.logger = logging.getLogger(__name__)
                self.logger.info("Tight encoding enabled")
            except ImportError as e:
                self.logger = logging.getLogger(__name__)
                self.logger.warning(f"Tight encoding unavailable: {e}")

        if enable_jpeg:
            try:
                from vnc_lib.jpeg_encoding import JPEGEncoder
                self.encoders[21] = JPEGEncoder()
                self.logger.info("JPEG encoding enabled")
            except ImportError as e:
                if not hasattr(self, 'logger'):
                    self.logger = logging.getLogger(__name__)
                self.logger.warning(f"JPEG encoding unavailable (PIL needed): {e}")

        if enable_h264:
            try:
                # H.264 is managed separately per-client
                self.logger.info("H.264 encoding enabled (per-client initialization)")
            except Exception as e:
                if not hasattr(self, 'logger'):
                    self.logger = logging.getLogger(__name__)
                self.logger.warning(f"H.264 encoding unavailable: {e}")

        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger(__name__)

        # Internal flag to avoid logging the same UltraVNC notice repeatedly
        self._tight_disabled_for_ultravnc_logged = False
        self._disable_tight_for_ultravnc = disable_tight_for_ultravnc

    def get_best_encoder(self, client_encodings: set[int],
                        content_type: str = "default") -> tuple[int, Encoder]:
        """
        Select best encoder based on client preferences and content

        Args:
            client_encodings: Set of encoding types supported by client
            content_type: Type of content ("static", "dynamic", "scrolling", "localhost", "default")

        Returns:
            (encoding_type, encoder) tuple
        """
        # Detect UltraVNC-style clients: they advertise Ultra (9) and/or TRLE (10)
        # encodings, which typical Tight/TigerVNC viewers do not.
        is_ultravnc_client = 9 in client_encodings or 10 in client_encodings

        # Preferred order based on content type using pattern matching (Python 3.13)
        match content_type:
            case "localhost":
                # For localhost connections, prefer Raw (maximum speed, no compression overhead)
                preference_order = [0]  # Raw only - compression unnecessary for localhost
            case "lan":
                # Current Hextile implementation is tile-raw and typically slower than
                # Raw while barely reducing payload size. For low-latency LAN usage,
                # prefer Raw first and keep compressed encoders as fallback.
                preference_order = [0, 6, 2, 5, 16]  # Raw, Zlib, RRE, Hextile, ZRLE
            case "static":
                # For static content, prefer compression
                preference_order = [7, 16, 5, 2, 0]  # Tight, ZRLE, Hextile, RRE, Raw
            case "dynamic":
                # For dynamic content, prefer speed with good compression
                preference_order = [7, 5, 2, 16, 0]  # Tight, Hextile, RRE, ZRLE, Raw
            case "scrolling":
                # For scrolling, try CopyRect first, then Tight
                preference_order = [1, 7, 5, 2, 16, 0]  # CopyRect, Tight, Hextile, RRE, ZRLE, Raw
            case "video":
                # For video/photos, prefer JPEG or H.264
                preference_order = [50, 21, 7, 16, 0]  # H.264, JPEG, Tight, ZRLE, Raw
            case "photo":
                # For photographic content, prefer JPEG
                preference_order = [21, 7, 16, 0]  # JPEG, Tight, ZRLE, Raw
            case _:
                # Default: balanced (Tight is best overall)
                preference_order = [7, 16, 5, 2, 1, 0]  # Tight, ZRLE, Hextile, RRE, CopyRect, Raw

        # For UltraVNC viewers, Tight encoding is currently unstable/buggy on the
        # client side even though our implementation passes TigerVNC and LibVNC
        # clients. To maximize compatibility, we can optionally disable Tight for
        # such clients (configurable via tight_disable_for_ultravnc).
        if self._disable_tight_for_ultravnc and is_ultravnc_client and 7 in self.encoders:
            preference_order = [enc for enc in preference_order if enc != 7]
            if not self._tight_disabled_for_ultravnc_logged:
                self.logger.info(
                    "Detected UltraVNC-like client (encodings include 9/10); "
                    "disabling Tight encoding for compatibility"
                )
                self._tight_disabled_for_ultravnc_logged = True

        # Find first available encoder
        for enc_type in preference_order:
            if enc_type in client_encodings and enc_type in self.encoders:
                self.logger.debug(f"Selected encoding: {enc_type} for content type: {content_type}")
                return enc_type, self.encoders[enc_type]

        # Fallback to raw
        return 0, self.encoders[0]
