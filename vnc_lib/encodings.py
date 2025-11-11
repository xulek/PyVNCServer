"""
VNC Encoding Implementations
Supports various RFB encodings for efficient data transmission
"""

import struct
import zlib
import logging
from typing import Protocol, TypeAlias
from collections.abc import Callable
from collections import deque


# Type aliases (Python 3.12+ would use 'type' statement)
PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes
Rectangle: TypeAlias = tuple[int, int, int, int]  # x, y, width, height


class BufferPool:
    """
    Simple buffer pool for reusing bytearrays across frames
    Reduces GC pressure and allocation overhead
    Pure Python, cross-platform implementation
    """

    def __init__(self, max_buffers: int = 10):
        """
        Initialize buffer pool

        Args:
            max_buffers: Maximum number of buffers to cache
        """
        self._pool: deque[bytearray] = deque(maxlen=max_buffers)
        self._max_buffers = max_buffers

    def get(self, size: int) -> bytearray:
        """
        Get a buffer from pool, or create new one if pool is empty

        Args:
            size: Minimum size needed

        Returns:
            bytearray of at least the requested size
        """
        # Try to find a buffer that's large enough
        for _ in range(len(self._pool)):
            buf = self._pool.popleft()
            if len(buf) >= size:
                # Clear the buffer (set length to 0 without deallocating)
                del buf[:]
                return buf
            # Return undersized buffer to pool
            self._pool.append(buf)

        # No suitable buffer found, create new one
        return bytearray(size)

    def put(self, buffer: bytearray) -> None:
        """
        Return a buffer to the pool

        Args:
            buffer: bytearray to return to pool
        """
        if len(self._pool) < self._max_buffers:
            # Clear buffer before returning to pool
            del buffer[:]
            self._pool.append(buffer)


# Global buffer pool instance (thread-safe due to GIL)
_buffer_pool = BufferPool(max_buffers=10)


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
        """
        Check if image shifted vertically by dy pixels
        Optimized with memoryview for faster comparisons
        """
        if abs(dy) >= height:
            return False

        # Use memoryview for zero-copy slicing (faster than bytes slicing)
        curr_view = memoryview(current)
        prev_view = memoryview(previous)

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

                # memoryview comparison is faster than bytes slicing
                if curr_view[curr_offset:curr_offset + line_size] == prev_view[prev_offset:prev_offset + line_size]:
                    matches += 1

        return matches >= check_lines * 0.8  # 80% match threshold

    def _is_horizontal_shift(self, current: PixelData, previous: PixelData,
                            width: int, height: int, bpp: int, dx: int) -> bool:
        """
        Check if image shifted horizontally by dx pixels
        Optimized with memoryview for faster comparisons
        """
        if abs(dx) >= width:
            return False

        # Use memoryview for zero-copy slicing
        curr_view = memoryview(current)
        prev_view = memoryview(previous)

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

                    # memoryview comparison is faster
                    if curr_view[curr_offset:curr_offset + bpp] == prev_view[prev_offset:prev_offset + bpp]:
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

    def __init__(self):
        self.logger = logging.getLogger(__name__)

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

        # Find background color (most common pixel)
        background = self._find_background(pixel_data, bytes_per_pixel)

        # Find rectangles of different colors
        subrects = self._find_subrectangles(
            pixel_data, width, height, bytes_per_pixel, background
        )

        # Build encoded data using buffer pool to reduce allocations
        # Estimate size: header (4) + background (bpp) + subrects * (bpp + 8)
        estimated_size = 4 + bytes_per_pixel + len(subrects) * (bytes_per_pixel + 8)
        result = _buffer_pool.get(estimated_size)

        result.extend(struct.pack(">I", len(subrects)))  # Number of subrectangles
        result.extend(background)  # Background pixel value

        for pixel_value, x, y, w, h in subrects:
            result.extend(pixel_value)
            result.extend(struct.pack(">HHHH", x, y, w, h))

        # Only use RRE if it's more efficient
        if len(result) < len(pixel_data):
            self.logger.debug(f"RRE: {len(pixel_data)} -> {len(result)} bytes")
            encoded = bytes(result)
            _buffer_pool.put(result)  # Return buffer to pool
            return encoded
        else:
            # Fallback to raw if RRE doesn't help
            _buffer_pool.put(result)  # Return buffer to pool
            return pixel_data

    def _find_background(self, pixel_data: PixelData, bpp: int) -> bytes:
        """Find most common pixel value (background)"""
        pixel_counts: dict[bytes, int] = {}

        for i in range(0, len(pixel_data), bpp):
            pixel = pixel_data[i:i+bpp]
            pixel_counts[pixel] = pixel_counts.get(pixel, 0) + 1

        # Return most common pixel
        return max(pixel_counts.items(), key=lambda x: x[1])[0] if pixel_counts else pixel_data[:bpp]

    def _find_subrectangles(self, pixel_data: PixelData, width: int,
                           height: int, bpp: int,
                           background: bytes) -> list[tuple[bytes, int, int, int, int]]:
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
        # Estimate size: worst case is raw encoding = original size + tile headers
        tiles_x = (width + self.TILE_SIZE - 1) // self.TILE_SIZE
        tiles_y = (height + self.TILE_SIZE - 1) // self.TILE_SIZE
        estimated_size = len(pixel_data) + tiles_x * tiles_y
        result = _buffer_pool.get(estimated_size)

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

        encoded = bytes(result)
        _buffer_pool.put(result)  # Return buffer to pool
        return encoded

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
        self.logger = logging.getLogger(__name__)

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        ZRLE encoding:
        1. Encode pixel data using run-length encoding
        2. Compress with zlib
        3. Prepend length header
        """
        # Convert to CPIXEL format (compact pixel format)
        cpixel_data = self._convert_to_cpixel(pixel_data, bytes_per_pixel)

        # Apply run-length encoding
        rle_data = self._apply_rle(cpixel_data, width, height)

        # Compress with zlib
        compressed = zlib.compress(rle_data, level=self.compression_level)

        # Prepend length (4 bytes, big-endian)
        result = struct.pack(">I", len(compressed)) + compressed

        self.logger.debug(
            f"ZRLE: {len(pixel_data)} -> {len(rle_data)} -> {len(compressed)} bytes"
        )

        return result

    def _convert_to_cpixel(self, pixel_data: PixelData, bpp: int) -> bytes:
        """
        Convert to CPIXEL format
        For 32-bit pixels, use 3 bytes (RGB) instead of 4 (RGBA)
        Optimized with pre-allocation and buffer pool
        """
        if bpp != 4:
            return pixel_data

        # Convert RGBA to RGB with pre-allocated buffer
        num_pixels = len(pixel_data) // 4
        result = _buffer_pool.get(num_pixels * 3)

        # Use memoryview for faster access
        src_view = memoryview(pixel_data)
        dst_offset = 0

        for i in range(0, len(pixel_data), 4):
            result.extend(src_view[i:i+3])  # Skip alpha channel

        encoded = bytes(result)
        _buffer_pool.put(result)
        return encoded

    def _apply_rle(self, pixel_data: PixelData, width: int, height: int) -> bytes:
        """
        Apply run-length encoding

        ZRLE uses a tile-based approach (64x64 tiles)
        For simplicity, this implementation works on the whole image
        """
        # Use buffer pool for result
        result = _buffer_pool.get(len(pixel_data) * 2)  # Worst case estimate
        bpp = 3  # CPIXEL format

        i = 0
        while i < len(pixel_data):
            pixel = pixel_data[i:i+bpp]
            run_length = 1

            # Count consecutive identical pixels
            while (i + run_length * bpp < len(pixel_data) and
                   pixel_data[i+run_length*bpp:i+(run_length+1)*bpp] == pixel):
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

            i += run_length * bpp

        encoded = bytes(result)
        _buffer_pool.put(result)
        return encoded


class EncoderManager:
    """
    Manages encoding selection based on client preferences
    and content analysis (Python 3.13 style)
    """

    def __init__(self):
        self.encoders: dict[int, Encoder] = {
            0: RawEncoder(),
            1: CopyRectEncoder(),  # CopyRect for scrolling/movement
            2: RREEncoder(),
            5: HextileEncoder(),
            16: ZRLEEncoder(),
        }
        self.logger = logging.getLogger(__name__)

    def get_best_encoder(self, client_encodings: set[int],
                        content_type: str = "default") -> tuple[int, Encoder]:
        """
        Select best encoder based on client preferences and content

        Args:
            client_encodings: Set of encoding types supported by client
            content_type: Type of content ("static", "dynamic", "scrolling", "default")

        Returns:
            (encoding_type, encoder) tuple
        """
        # Preferred order based on content type using pattern matching (Python 3.13)
        match content_type:
            case "static":
                # For static content, prefer compression
                preference_order = [16, 5, 2, 0]  # ZRLE, Hextile, RRE, Raw
            case "dynamic":
                # For dynamic content, prefer speed
                preference_order = [5, 2, 0, 16]  # Hextile, RRE, Raw, ZRLE
            case "scrolling":
                # For scrolling, try CopyRect first
                preference_order = [1, 5, 2, 16, 0]  # CopyRect, Hextile, RRE, ZRLE, Raw
            case _:
                # Default: balanced
                preference_order = [16, 5, 2, 1, 0]

        # Find first available encoder
        for enc_type in preference_order:
            if enc_type in client_encodings and enc_type in self.encoders:
                self.logger.debug(f"Selected encoding: {enc_type} for content type: {content_type}")
                return enc_type, self.encoders[enc_type]

        # Fallback to raw
        return 0, self.encoders[0]
