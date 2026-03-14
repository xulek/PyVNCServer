"""
VNC Encoding Implementations
Supports various RFB encodings for efficient data transmission
"""

import struct
import sys
import zlib
import logging
from typing import Protocol, TypeAlias
from collections.abc import Callable, Iterable


# Type aliases (Python 3.12+ would use 'type' statement)
PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes
Rectangle: TypeAlias = tuple[int, int, int, int]  # x, y, width, height


_ENCODING_NAME_MAP: dict[int, str] = {
    0: "Raw",
    1: "CopyRect",
    2: "RRE",
    5: "Hextile",
    6: "Zlib",
    7: "Tight",
    16: "ZRLE",
    21: "JPEG",
    50: "H.264",
    9: "Ultra",
    10: "TRLE",
    -223: "DesktopSize",
    -224: "LastRect",
    -232: "PointerPos",
    -239: "Cursor",
    -308: "ExtendedDesktopSize",
    -314: "ContinuousUpdates",
}


def encoding_name(enc_type: int) -> str:
    """
    Return human-readable name for an encoding/pseudo-encoding id.
    """
    if enc_type in _ENCODING_NAME_MAP:
        return _ENCODING_NAME_MAP[enc_type]

    # Tight JPEG quality pseudo-encodings: -23..-32 (9..0)
    if -32 <= enc_type <= -23:
        quality_level = enc_type + 32
        return f"JPEGQualityLevel{quality_level}"

    # Tight compression level pseudo-encodings: -247..-256 (9..0)
    if -256 <= enc_type <= -247:
        compress_level = enc_type + 256
        return f"CompressLevel{compress_level}"

    return f"Unknown({enc_type})"


def _unique_encoding_order(encodings: Iterable[int]) -> list[int]:
    """
    Preserve first-seen order for ordered inputs while still deduplicating.

    Sets remain accepted for compatibility, but their iteration order should not
    be relied on when client preference order matters.
    """
    seen: set[int] = set()
    ordered: list[int] = []
    for enc in encodings:
        enc_int = int(enc)
        if enc_int in seen:
            continue
        seen.add(enc_int)
        ordered.append(enc_int)
    return ordered


def format_encoding_list(encodings: Iterable[int]) -> str:
    """
    Format encoding ids as a readable comma-separated list.
    """
    unique_ordered = _unique_encoding_order(encodings)
    if not unique_ordered:
        return "none"
    return ", ".join(f"{encoding_name(enc)} ({enc})" for enc in unique_ordered)


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
        self.bytes_per_pixel: int = 0

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        CopyRect encoding - finds matching rectangles from previous frame

        Returns: struct.pack(">HH", src_x, src_y) if match found, else pixel_data
        """
        if self.previous_frame is None or width != self.frame_width or height != self.frame_height:
            self.commit_frame(pixel_data, width, height, bytes_per_pixel)
            # First frame - no copy possible
            return pixel_data

        match = self.find_source_for_region(
            pixel_data,
            width,
            height,
            0,
            0,
            width,
            height,
            bytes_per_pixel,
        )
        self.commit_frame(pixel_data, width, height, bytes_per_pixel)

        if match:
            src_x, src_y = match
            self.logger.debug(f"CopyRect: source ({src_x}, {src_y})")
            return struct.pack(">HH", src_x, src_y)

        # No match found, fallback to raw
        return pixel_data

    def reset(self) -> None:
        """Drop cached framebuffer state."""
        self.previous_frame = None
        self.frame_width = 0
        self.frame_height = 0
        self.bytes_per_pixel = 0

    def commit_frame(self, pixel_data: PixelData, width: int, height: int,
                     bytes_per_pixel: int) -> None:
        """Store the framebuffer last known to be present on the client."""
        self.previous_frame = pixel_data
        self.frame_width = width
        self.frame_height = height
        self.bytes_per_pixel = bytes_per_pixel

    def find_source_for_region(
        self,
        current_frame: PixelData,
        fb_width: int,
        fb_height: int,
        target_x: int,
        target_y: int,
        target_width: int,
        target_height: int,
        bytes_per_pixel: int,
        request_region: Rectangle | None = None,
    ) -> tuple[int, int] | None:
        """
        Find a safe CopyRect source in the previous framebuffer for the target region.

        Returns a `(src_x, src_y)` pair only when the exact region already exists in the
        previous framebuffer and the copy stays within the requested client region.
        """
        if (
            self.previous_frame is None
            or fb_width != self.frame_width
            or fb_height != self.frame_height
            or bytes_per_pixel != self.bytes_per_pixel
            or target_width <= 0
            or target_height <= 0
        ):
            return None

        target_region = self._extract_region(
            current_frame,
            fb_width,
            fb_height,
            target_x,
            target_y,
            target_width,
            target_height,
            bytes_per_pixel,
        )
        if not target_region:
            return None

        for src_x, src_y in self._candidate_sources(
            fb_width,
            fb_height,
            target_x,
            target_y,
            target_width,
            target_height,
        ):
            if request_region is not None and not self._region_within_request(
                src_x, src_y, target_width, target_height, request_region
            ):
                continue
            if src_x == target_x and src_y == target_y:
                continue
            if self._region_matches_previous(
                target_region,
                src_x,
                src_y,
                fb_width,
                fb_height,
                target_width,
                target_height,
                bytes_per_pixel,
            ):
                return src_x, src_y

        return None

    def encode_copyrect(
        self,
        current_frame: PixelData,
        fb_width: int,
        fb_height: int,
        target_x: int,
        target_y: int,
        target_width: int,
        target_height: int,
        bytes_per_pixel: int,
        request_region: Rectangle | None = None,
    ) -> bytes | None:
        """Encode a CopyRect payload for a specific target rectangle, or return None."""
        match = self.find_source_for_region(
            current_frame,
            fb_width,
            fb_height,
            target_x,
            target_y,
            target_width,
            target_height,
            bytes_per_pixel,
            request_region=request_region,
        )
        if match is None:
            return None
        src_x, src_y = match
        self.logger.debug(
            "CopyRect: target (%d, %d, %d, %d) <- source (%d, %d)",
            target_x,
            target_y,
            target_width,
            target_height,
            src_x,
            src_y,
        )
        return struct.pack(">HH", src_x, src_y)

    def _extract_region(self, pixel_data: PixelData, fb_width: int, fb_height: int,
                        x: int, y: int, width: int, height: int, bpp: int) -> bytes:
        if (
            width <= 0
            or height <= 0
            or bpp <= 0
            or x < 0
            or y < 0
            or x + width > fb_width
            or y + height > fb_height
        ):
            return b""

        row_size = width * bpp
        result = bytearray(height * row_size)
        dst_offset = 0
        for row in range(height):
            src_offset = ((y + row) * fb_width + x) * bpp
            result[dst_offset:dst_offset + row_size] = pixel_data[src_offset:src_offset + row_size]
            dst_offset += row_size
        return bytes(result)

    def _region_within_request(self, src_x: int, src_y: int, width: int, height: int,
                               request_region: Rectangle) -> bool:
        req_x, req_y, req_width, req_height = request_region
        return (
            src_x >= req_x
            and src_y >= req_y
            and src_x + width <= req_x + req_width
            and src_y + height <= req_y + req_height
        )

    def _candidate_sources(self, fb_width: int, fb_height: int,
                           target_x: int, target_y: int,
                           target_width: int, target_height: int) -> list[tuple[int, int]]:
        """
        Generate conservative candidate sources for window moves and scrolling.

        CopyRect support here is intentionally conservative: prefer common local shifts
        and full-width/full-height scroll regions over expensive exhaustive search.
        """
        candidates: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()

        def add_candidate(src_x: int, src_y: int) -> None:
            if (
                src_x < 0
                or src_y < 0
                or src_x + target_width > fb_width
                or src_y + target_height > fb_height
            ):
                return
            candidate = (src_x, src_y)
            if candidate in seen:
                return
            seen.add(candidate)
            candidates.append(candidate)

        # Common scroll/window-move deltas near the current position.
        deltas = (
            -128, -96, -64, -48, -32, -24, -16, -12, -10, -8, -6, -5, -4, -3, -2, -1,
            1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 24, 32, 48, 64, 96, 128,
        )
        for delta in deltas:
            add_candidate(target_x + delta, target_y)
            add_candidate(target_x, target_y + delta)

        # Full-width and full-height regions are common scroll cases; search more broadly.
        if target_width == fb_width:
            lower = max(0, target_y - min(256, fb_height))
            upper = min(fb_height - target_height, target_y + min(256, fb_height - target_height))
            for src_y in range(lower, upper + 1):
                add_candidate(0, src_y)
        if target_height == fb_height:
            lower = max(0, target_x - min(256, fb_width))
            upper = min(fb_width - target_width, target_x + min(256, fb_width - target_width))
            for src_x in range(lower, upper + 1):
                add_candidate(src_x, 0)

        return candidates

    def _region_matches_previous(
        self,
        target_region: bytes,
        src_x: int,
        src_y: int,
        fb_width: int,
        fb_height: int,
        target_width: int,
        target_height: int,
        bpp: int,
    ) -> bool:
        prev_region = self._extract_region(
            self.previous_frame or b"",
            fb_width,
            fb_height,
            src_x,
            src_y,
            target_width,
            target_height,
            bpp,
        )
        if not prev_region or len(prev_region) != len(target_region):
            return False

        row_size = target_width * bpp
        if row_size <= 0:
            return False

        if prev_region[:row_size] != target_region[:row_size]:
            return False
        if prev_region[-row_size:] != target_region[-row_size:]:
            return False
        return prev_region == target_region

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
        self.tile_size = 64
        self.fast_raw_unique_threshold = 24
        self.fast_raw_run_ratio_threshold = 0.12
        self.fast_palette_max_colors = 8
        self._compression_strategy = zlib.Z_DEFAULT_STRATEGY

    def set_compression_level(self, level: int) -> None:
        """Update compression level and reset stream state only when it actually changes."""
        new_level = max(1, min(9, int(level)))
        if new_level != self.compression_level:
            self.compression_level = new_level
            self._compressor = zlib.compressobj(
                level=self.compression_level,
                strategy=self._compression_strategy,
            )

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int, pixel_format: dict | None = None) -> EncodedData:
        """
        ZRLE encoding:
        1. Convert pixels to CPIXEL format when required by RFC 6143
        2. Encode 64x64 tiles using TRLE-compatible subencodings
        3. Compress with a persistent zlib stream
        4. Prepend a 4-byte length header
        """
        encoded_tiles, tile_stats = self._encode_tiles(pixel_data, width, height, bytes_per_pixel, pixel_format)
        strategy = self._choose_compression_strategy(tile_stats)
        if strategy != self._compression_strategy:
            self._compression_strategy = strategy
            self._compressor = zlib.compressobj(
                level=self.compression_level,
                strategy=self._compression_strategy,
            )
        compressed = (
            self._compressor.compress(encoded_tiles)
            + self._compressor.flush(zlib.Z_SYNC_FLUSH)
        )
        self.logger.debug(
            "ZRLE: %d -> %d -> %d bytes",
            len(pixel_data),
            len(encoded_tiles),
            len(compressed),
        )
        return struct.pack(">I", len(compressed)) + compressed

    def _encode_tiles(self, pixel_data: PixelData, width: int, height: int,
                      bytes_per_pixel: int, pixel_format: dict | None) -> tuple[bytes, dict[str, int]]:
        if width <= 0 or height <= 0 or bytes_per_pixel <= 0 or not pixel_data:
            return b"", {"raw": 0, "solid": 0, "palette": 0, "rle": 0, "total": 0}

        if bytes_per_pixel == 4:
            cpixel_byte_offset = self._cpixel_byte_offset(pixel_format)
            if cpixel_byte_offset is not None:
                if cpixel_byte_offset == 0 and sys.byteorder == "little":
                    return self._encode_tiles_32bpp_native(pixel_data, width, height)
                return self._encode_tiles_32bpp(pixel_data, width, height, cpixel_byte_offset)

        result = bytearray()
        stats = {"raw": 0, "solid": 0, "palette": 0, "rle": 0, "total": 0}
        for tile_y in range(0, height, self.tile_size):
            tile_height = min(self.tile_size, height - tile_y)
            for tile_x in range(0, width, self.tile_size):
                tile_width = min(self.tile_size, width - tile_x)
                tile_data = self._extract_tile(
                    pixel_data,
                    width,
                    tile_x,
                    tile_y,
                    tile_width,
                    tile_height,
                    bytes_per_pixel,
                )
                cpixel_data, cpixel_bpp = self._convert_to_cpixel(
                    tile_data,
                    bytes_per_pixel,
                    pixel_format=pixel_format,
                )
                tile_payload = self._encode_tile(cpixel_data, tile_width, tile_height, cpixel_bpp)
                self._update_tile_stats(stats, tile_payload)
                result.extend(tile_payload)
        return bytes(result), stats

    def _encode_tiles_32bpp(self, pixel_data: PixelData, width: int, height: int,
                            byte_offset: int) -> tuple[bytes, dict[str, int]]:
        result = bytearray()
        view = memoryview(pixel_data)
        stats = {"raw": 0, "solid": 0, "palette": 0, "rle": 0, "total": 0}
        for tile_y in range(0, height, self.tile_size):
            tile_height = min(self.tile_size, height - tile_y)
            for tile_x in range(0, width, self.tile_size):
                tile_width = min(self.tile_size, width - tile_x)
                tile_payload = self._encode_tile_32bpp(
                    view,
                    width,
                    tile_x,
                    tile_y,
                    tile_width,
                    tile_height,
                    byte_offset,
                )
                self._update_tile_stats(stats, tile_payload)
                result.extend(tile_payload)
        return bytes(result), stats

    def _encode_tiles_32bpp_native(self, pixel_data: PixelData, width: int, height: int) -> tuple[bytes, dict[str, int]]:
        result = bytearray()
        pixel_words = memoryview(pixel_data).cast("I")
        stats = {"raw": 0, "solid": 0, "palette": 0, "rle": 0, "total": 0}
        for tile_y in range(0, height, self.tile_size):
            tile_height = min(self.tile_size, height - tile_y)
            for tile_x in range(0, width, self.tile_size):
                tile_width = min(self.tile_size, width - tile_x)
                tile_payload = self._encode_tile_32bpp_native(
                    pixel_data,
                    pixel_words,
                    width,
                    tile_x,
                    tile_y,
                    tile_width,
                    tile_height,
                )
                self._update_tile_stats(stats, tile_payload)
                result.extend(tile_payload)
        return bytes(result), stats

    def _update_tile_stats(self, stats: dict[str, int], tile_payload: bytes) -> None:
        if not tile_payload:
            return
        stats["total"] += 1
        subencoding = tile_payload[0]
        if subencoding == 0:
            stats["raw"] += 1
        elif subencoding == 1:
            stats["solid"] += 1
        elif 2 <= subencoding <= 16:
            stats["palette"] += 1
        else:
            stats["rle"] += 1

    def _choose_compression_strategy(self, tile_stats: dict[str, int]) -> int:
        total = tile_stats.get("total", 0)
        if total <= 0:
            return zlib.Z_DEFAULT_STRATEGY
        raw_ratio = tile_stats.get("raw", 0) / total
        if raw_ratio >= 0.7:
            return zlib.Z_HUFFMAN_ONLY
        return zlib.Z_DEFAULT_STRATEGY

    def _extract_tile(self, pixel_data: PixelData, fb_width: int,
                      tile_x: int, tile_y: int, tile_width: int,
                      tile_height: int, bpp: int) -> bytes:
        tile = bytearray(tile_width * tile_height * bpp)
        row_size = tile_width * bpp
        dst_offset = 0
        for row in range(tile_height):
            src_offset = ((tile_y + row) * fb_width + tile_x) * bpp
            tile[dst_offset:dst_offset + row_size] = pixel_data[src_offset:src_offset + row_size]
            dst_offset += row_size
        return bytes(tile)

    def _convert_to_cpixel(self, pixel_data: PixelData, bpp: int,
                           pixel_format: dict | None = None) -> tuple[bytes, int]:
        """
        Convert to CPIXEL format
        For 32-bit pixels, use 3 bytes (RGB) instead of 4 (RGBA)
        """
        if bpp in (1, 2, 3):
            return pixel_data, bpp

        if bpp == 4:
            byte_offset = self._cpixel_byte_offset(pixel_format)
            if byte_offset is None:
                return pixel_data, bpp

            num_pixels = len(pixel_data) // 4
            result = bytearray(num_pixels * 3)
            src_view = memoryview(pixel_data)
            dst_view = memoryview(result)
            dst_view[0::3] = src_view[byte_offset + 0::4]
            dst_view[1::3] = src_view[byte_offset + 1::4]
            dst_view[2::3] = src_view[byte_offset + 2::4]
            return bytes(result), 3

        self.logger.warning(f"ZRLE: unsupported bpp {bpp}, treating as single-byte pixels")
        return pixel_data, 1

    def _cpixel_byte_offset(self, pixel_format: dict | None) -> int | None:
        if not pixel_format:
            return 0

        bits = []
        for max_key, shift_key in (
            ("red_max", "red_shift"),
            ("green_max", "green_shift"),
            ("blue_max", "blue_shift"),
        ):
            channel_max = int(pixel_format.get(max_key, 0))
            channel_shift = int(pixel_format.get(shift_key, 0))
            if channel_max <= 0:
                return None
            bits.append(channel_shift + channel_max.bit_length())

        if max(bits) <= 24:
            return 0
        if min(int(pixel_format.get(key, 0)) for key in ("red_shift", "green_shift", "blue_shift")) >= 8:
            return 1
        return None

    def _encode_tile(self, pixel_data: PixelData, width: int, height: int,
                     pixel_size: int) -> bytes:
        if not pixel_data:
            return b"\x00"

        pixel_count = width * height
        if pixel_count <= 0:
            return b"\x00"

        if self._is_solid_tile(pixel_data, pixel_size):
            return bytes([1]) + pixel_data[:pixel_size]

        analysis = self._analyze_tile_fast(pixel_data, pixel_size, pixel_count)
        if analysis["prefer_raw"]:
            return bytes([0]) + pixel_data

        pixels = self._split_pixels(pixel_data, pixel_size)
        if not pixels:
            return b"\x00"

        palette_limit = 16 if analysis["palette_candidate"] else 127
        palette = self._palette_in_order(pixels, limit=palette_limit)
        if len(palette) == 1:
            return bytes([1]) + self._pixel_to_bytes(palette[0], pixel_size)

        if 2 <= len(palette) <= 16:
            packed_payload = self._encode_packed_palette(pixels, palette, width, height)
            return (
                bytes([len(palette)])
                + b"".join(self._pixel_to_bytes(pixel, pixel_size) for pixel in palette)
                + packed_payload
            )

        if analysis["run_friendly"]:
            plain_rle_payload = self._encode_plain_rle(pixels, pixel_size)
            plain_rle_candidate = bytes([128]) + plain_rle_payload
            if len(palette) < 2:
                return plain_rle_candidate

        if 2 <= len(palette) <= 127 and analysis["run_friendly"]:
            palette_rle_payload = self._encode_palette_rle(pixels, palette)
            return (
                bytes([128 + len(palette)])
                + b"".join(self._pixel_to_bytes(pixel, pixel_size) for pixel in palette)
                + palette_rle_payload
            )

        if analysis["run_friendly"]:
            return bytes([128]) + self._encode_plain_rle(pixels, pixel_size)

        return bytes([0]) + pixel_data

    def _encode_tile_32bpp(self, frame_view: memoryview, fb_width: int,
                           tile_x: int, tile_y: int, width: int, height: int,
                           byte_offset: int) -> bytes:
        pixel_count = width * height
        if pixel_count <= 0:
            return b"\x00"

        solid_pixel = self._solid_pixel_32bpp(
            frame_view,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
            byte_offset,
        )
        if solid_pixel is not None:
            return bytes([1]) + self._pixel_to_bytes(solid_pixel, 3)

        analysis = self._analyze_tile_fast_32bpp(
            frame_view,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
            byte_offset,
            pixel_count,
        )
        if analysis["prefer_raw"]:
            return bytes([0]) + self._build_raw_tile_32bpp(
                frame_view,
                fb_width,
                tile_x,
                tile_y,
                width,
                height,
                byte_offset,
            )

        pixels = self._extract_tile_pixels_32bpp(
            frame_view,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
            byte_offset,
        )
        if not pixels:
            return b"\x00"

        palette_limit = 16 if analysis["palette_candidate"] else 127
        palette = self._palette_in_order(pixels, limit=palette_limit)
        if len(palette) == 1:
            return bytes([1]) + self._pixel_to_bytes(palette[0], 3)

        if 2 <= len(palette) <= 16:
            packed_payload = self._encode_packed_palette(pixels, palette, width, height)
            return (
                bytes([len(palette)])
                + b"".join(self._pixel_to_bytes(pixel, 3) for pixel in palette)
                + packed_payload
            )

        if analysis["run_friendly"]:
            plain_rle_payload = self._encode_plain_rle(pixels, 3)
            plain_rle_candidate = bytes([128]) + plain_rle_payload
            if len(palette) < 2:
                return plain_rle_candidate

        if 2 <= len(palette) <= 127 and analysis["run_friendly"]:
            palette_rle_payload = self._encode_palette_rle(pixels, palette)
            return (
                bytes([128 + len(palette)])
                + b"".join(self._pixel_to_bytes(pixel, 3) for pixel in palette)
                + palette_rle_payload
            )

        if analysis["run_friendly"]:
            return bytes([128]) + self._encode_plain_rle(pixels, 3)

        return bytes([0]) + self._build_raw_tile_32bpp(
            frame_view,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
            byte_offset,
        )

    def _encode_tile_32bpp_native(self, frame_bytes: bytes, pixel_words: memoryview,
                                  fb_width: int, tile_x: int, tile_y: int,
                                  width: int, height: int) -> bytes:
        pixel_count = width * height
        if pixel_count <= 0:
            return b"\x00"

        solid_pixel = self._solid_pixel_32bpp_native(
            pixel_words,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
        )
        if solid_pixel is not None:
            return bytes([1]) + self._pixel32_native_to_cpixel_bytes(solid_pixel)

        analysis = self._analyze_tile_fast_32bpp_native(
            pixel_words,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
            pixel_count,
        )
        if analysis["palette_candidate"]:
            packed_palette = self._try_encode_packed_palette_tile_32bpp_native(
                pixel_words,
                fb_width,
                tile_x,
                tile_y,
                width,
                height,
            )
            if packed_palette is not None:
                return packed_palette

        if analysis["prefer_raw"]:
            return bytes([0]) + self._build_raw_tile_32bpp_native(
                frame_bytes,
                fb_width,
                tile_x,
                tile_y,
                width,
                height,
            )

        pixels = self._extract_tile_pixels_32bpp_native(
            pixel_words,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
        )
        if not pixels:
            return b"\x00"

        palette_limit = 16 if analysis["palette_candidate"] else 127
        palette = self._palette_in_order(pixels, limit=palette_limit)
        if len(palette) == 1:
            return bytes([1]) + self._pixel32_native_to_cpixel_bytes(palette[0])

        if 2 <= len(palette) <= 16:
            packed_payload = self._encode_packed_palette(pixels, palette, width, height)
            return (
                bytes([len(palette)])
                + b"".join(self._pixel32_native_to_cpixel_bytes(pixel) for pixel in palette)
                + packed_payload
            )

        if analysis["run_friendly"]:
            plain_rle_payload = self._encode_plain_rle_32bpp_native(pixels)
            plain_rle_candidate = bytes([128]) + plain_rle_payload
            if len(palette) < 2:
                return plain_rle_candidate

        if 2 <= len(palette) <= 127 and analysis["run_friendly"]:
            palette_rle_payload = self._encode_palette_rle(pixels, palette)
            return (
                bytes([128 + len(palette)])
                + b"".join(self._pixel32_native_to_cpixel_bytes(pixel) for pixel in palette)
                + palette_rle_payload
            )

        if analysis["run_friendly"]:
            return bytes([128]) + self._encode_plain_rle_32bpp_native(pixels)

        return bytes([0]) + self._build_raw_tile_32bpp_native(
            frame_bytes,
            fb_width,
            tile_x,
            tile_y,
            width,
            height,
        )

    def _solid_pixel_32bpp_native(self, pixel_words: memoryview, fb_width: int,
                                  tile_x: int, tile_y: int, width: int,
                                  height: int) -> int | None:
        first_index = tile_y * fb_width + tile_x
        first_pixel = int(pixel_words[first_index]) & 0x00FFFFFF
        row_start = first_index
        for _ in range(height):
            row_end = row_start + width
            for pixel in pixel_words[row_start:row_end]:
                if (int(pixel) & 0x00FFFFFF) != first_pixel:
                    return None
            row_start += fb_width
        return first_pixel

    def _analyze_tile_fast_32bpp_native(self, pixel_words: memoryview, fb_width: int,
                                        tile_x: int, tile_y: int, width: int,
                                        height: int, pixel_count: int) -> dict[str, bool]:
        if pixel_count <= 64:
            return {
                "prefer_raw": False,
                "run_friendly": True,
                "palette_candidate": True,
            }

        sample_pixels = min(pixel_count, 128)
        step = max(1, pixel_count // sample_pixels)
        row = 0
        col = 0
        first_index = tile_y * fb_width + tile_x
        first_pixel = int(pixel_words[first_index]) & 0x00FFFFFF
        previous = first_pixel
        unique = {first_pixel}
        repeat_pairs = 0
        samples_seen = 1

        for _ in range(1, sample_pixels):
            col += step
            while col >= width:
                col -= width
                row += 1
                if row >= height:
                    row = height - 1
                    col = width - 1
                    break
            pixel = int(pixel_words[(tile_y + row) * fb_width + tile_x + col]) & 0x00FFFFFF
            if pixel == previous:
                repeat_pairs += 1
            previous = pixel
            unique.add(pixel)
            samples_seen += 1
            if len(unique) > self.fast_raw_unique_threshold:
                return {
                    "prefer_raw": True,
                    "run_friendly": False,
                    "palette_candidate": False,
                }

        run_ratio = repeat_pairs / max(1, samples_seen - 1)
        palette_candidate = len(unique) <= self.fast_palette_max_colors
        prefer_raw = (not palette_candidate) and run_ratio < self.fast_raw_run_ratio_threshold
        return {
            "prefer_raw": prefer_raw,
            "run_friendly": run_ratio >= self.fast_raw_run_ratio_threshold,
            "palette_candidate": palette_candidate,
        }

    def _extract_tile_pixels_32bpp_native(self, pixel_words: memoryview, fb_width: int,
                                          tile_x: int, tile_y: int, width: int,
                                          height: int) -> list[int]:
        pixels: list[int] = []
        pixels_extend = pixels.extend
        row_start = tile_y * fb_width + tile_x
        for _ in range(height):
            row_end = row_start + width
            pixels_extend((int(pixel) & 0x00FFFFFF) for pixel in pixel_words[row_start:row_end])
            row_start += fb_width
        return pixels

    def _try_encode_packed_palette_tile_32bpp_native(
        self,
        pixel_words: memoryview,
        fb_width: int,
        tile_x: int,
        tile_y: int,
        width: int,
        height: int,
    ) -> bytes | None:
        palette: list[int] = []
        palette_index: dict[int, int] = {}
        row_indices: list[list[int]] = []
        row_start = tile_y * fb_width + tile_x

        for _ in range(height):
            row_end = row_start + width
            indices_row: list[int] = []
            for pixel in pixel_words[row_start:row_end]:
                pixel_value = int(pixel) & 0x00FFFFFF
                idx = palette_index.get(pixel_value)
                if idx is None:
                    idx = len(palette)
                    if idx >= 16:
                        return None
                    palette_index[pixel_value] = idx
                    palette.append(pixel_value)
                indices_row.append(idx)
            row_indices.append(indices_row)
            row_start += fb_width

        palette_size = len(palette)
        if palette_size == 0:
            return b"\x00"
        if palette_size == 1:
            return bytes([1]) + self._pixel32_native_to_cpixel_bytes(palette[0])

        if palette_size == 2:
            bits_per_index = 1
        elif palette_size <= 4:
            bits_per_index = 2
        else:
            bits_per_index = 4

        packed_payload = bytearray()
        for indices_row in row_indices:
            current_byte = 0
            used_bits = 0
            for idx in indices_row:
                current_byte = (current_byte << bits_per_index) | idx
                used_bits += bits_per_index
                if used_bits == 8:
                    packed_payload.append(current_byte)
                    current_byte = 0
                    used_bits = 0
            if used_bits:
                current_byte <<= (8 - used_bits)
                packed_payload.append(current_byte)

        return (
            bytes([palette_size])
            + b"".join(self._pixel32_native_to_cpixel_bytes(pixel) for pixel in palette)
            + bytes(packed_payload)
        )

    def _build_raw_tile_32bpp_native(self, frame_bytes: bytes, fb_width: int,
                                     tile_x: int, tile_y: int, width: int,
                                     height: int) -> bytes:
        frame_view = memoryview(frame_bytes)
        result = bytearray(width * height * 3)
        dst_view = memoryview(result)
        row_stride = fb_width * 4
        src_row_start = ((tile_y * fb_width) + tile_x) * 4
        dst_row_start = 0
        for _ in range(height):
            row_slice = frame_view[src_row_start:src_row_start + (width * 4)]
            row_dst = dst_view[dst_row_start:dst_row_start + (width * 3)]
            row_dst[0::3] = row_slice[0::4]
            row_dst[1::3] = row_slice[1::4]
            row_dst[2::3] = row_slice[2::4]
            src_row_start += row_stride
            dst_row_start += width * 3
        return bytes(result)

    def _encode_plain_rle_32bpp_native(self, pixels: list[int]) -> bytes:
        result = bytearray()
        index = 0
        while index < len(pixels):
            pixel = pixels[index]
            run_length = 1
            while index + run_length < len(pixels) and pixels[index + run_length] == pixel:
                run_length += 1
            result.extend(self._pixel32_native_to_cpixel_bytes(pixel))
            self._encode_run_length_into(result, run_length)
            index += run_length
        return bytes(result)

    def _pixel32_native_to_cpixel_bytes(self, pixel: int) -> bytes:
        return pixel.to_bytes(4, "little")[:3]

    def _solid_pixel_32bpp(self, frame_view: memoryview, fb_width: int,
                           tile_x: int, tile_y: int, width: int, height: int,
                           byte_offset: int) -> int | None:
        first_offset = ((tile_y * fb_width) + tile_x) * 4 + byte_offset
        first_pixel = (
            (frame_view[first_offset] << 16)
            | (frame_view[first_offset + 1] << 8)
            | frame_view[first_offset + 2]
        )

        row_stride = fb_width * 4
        row_start = ((tile_y * fb_width) + tile_x) * 4 + byte_offset
        for _ in range(height):
            offset = row_start
            for _ in range(width):
                pixel = (
                    (frame_view[offset] << 16)
                    | (frame_view[offset + 1] << 8)
                    | frame_view[offset + 2]
                )
                if pixel != first_pixel:
                    return None
                offset += 4
            row_start += row_stride
        return first_pixel

    def _analyze_tile_fast_32bpp(self, frame_view: memoryview, fb_width: int,
                                 tile_x: int, tile_y: int, width: int, height: int,
                                 byte_offset: int, pixel_count: int) -> dict[str, bool]:
        if pixel_count <= 64:
            return {
                "prefer_raw": False,
                "run_friendly": True,
                "palette_candidate": True,
            }

        sample_pixels = min(pixel_count, 128)
        step = max(1, pixel_count // sample_pixels)
        row_stride = fb_width * 4
        row = 0
        col = 0
        first_offset = ((tile_y * fb_width) + tile_x) * 4 + byte_offset
        first_pixel = (
            (frame_view[first_offset] << 16)
            | (frame_view[first_offset + 1] << 8)
            | frame_view[first_offset + 2]
        )
        previous = first_pixel
        unique = {first_pixel}
        repeat_pairs = 0
        samples_seen = 1

        for _ in range(1, sample_pixels):
            col += step
            while col >= width:
                col -= width
                row += 1
                if row >= height:
                    row = height - 1
                    col = width - 1
                    break
            offset = (((tile_y + row) * fb_width) + tile_x + col) * 4 + byte_offset
            pixel = (
                (frame_view[offset] << 16)
                | (frame_view[offset + 1] << 8)
                | frame_view[offset + 2]
            )
            if pixel == previous:
                repeat_pairs += 1
            previous = pixel
            unique.add(pixel)
            samples_seen += 1
            if len(unique) > self.fast_raw_unique_threshold:
                return {
                    "prefer_raw": True,
                    "run_friendly": False,
                    "palette_candidate": False,
                }

        run_ratio = repeat_pairs / max(1, samples_seen - 1)
        palette_candidate = len(unique) <= self.fast_palette_max_colors
        prefer_raw = (not palette_candidate) and run_ratio < self.fast_raw_run_ratio_threshold
        return {
            "prefer_raw": prefer_raw,
            "run_friendly": run_ratio >= self.fast_raw_run_ratio_threshold,
            "palette_candidate": palette_candidate,
        }

    def _extract_tile_pixels_32bpp(self, frame_view: memoryview, fb_width: int,
                                   tile_x: int, tile_y: int, width: int, height: int,
                                   byte_offset: int) -> list[int]:
        pixels: list[int] = []
        pixels_extend = pixels.extend
        row_stride = fb_width * 4
        row_start = ((tile_y * fb_width) + tile_x) * 4 + byte_offset
        for _ in range(height):
            row_pixels = [
                (frame_view[offset] << 16)
                | (frame_view[offset + 1] << 8)
                | frame_view[offset + 2]
                for offset in range(row_start, row_start + (width * 4), 4)
            ]
            pixels_extend(row_pixels)
            row_start += row_stride
        return pixels

    def _build_raw_tile_32bpp(self, frame_view: memoryview, fb_width: int,
                              tile_x: int, tile_y: int, width: int, height: int,
                              byte_offset: int) -> bytes:
        result = bytearray(width * height * 3)
        dst_view = memoryview(result)
        row_stride = fb_width * 4
        src_row_start = ((tile_y * fb_width) + tile_x) * 4
        dst_row_start = 0
        for _ in range(height):
            row_slice = frame_view[src_row_start:src_row_start + (width * 4)]
            row_dst = dst_view[dst_row_start:dst_row_start + (width * 3)]
            row_dst[0::3] = row_slice[byte_offset + 0::4]
            row_dst[1::3] = row_slice[byte_offset + 1::4]
            row_dst[2::3] = row_slice[byte_offset + 2::4]
            src_row_start += row_stride
            dst_row_start += width * 3
        return bytes(result)

    def _is_solid_tile(self, pixel_data: PixelData, pixel_size: int) -> bool:
        if len(pixel_data) <= pixel_size:
            return True
        first = pixel_data[:pixel_size]
        for offset in range(pixel_size, len(pixel_data), pixel_size):
            if pixel_data[offset:offset + pixel_size] != first:
                return False
        return True

    def _analyze_tile_fast(self, pixel_data: PixelData, pixel_size: int,
                           pixel_count: int) -> dict[str, bool]:
        """Cheap tile heuristics to avoid expensive TRLE analysis on obviously high-entropy tiles."""
        if pixel_count <= 64:
            return {
                "prefer_raw": False,
                "run_friendly": True,
                "palette_candidate": True,
            }

        view = memoryview(pixel_data)
        sample_pixels = min(pixel_count, 128)
        step = max(1, pixel_count // sample_pixels)
        sample_step = step * pixel_size
        first = bytes(view[:pixel_size])
        previous = first
        unique: set[bytes] = {first}
        repeat_pairs = 0
        samples_seen = 1

        for offset in range(sample_step, len(pixel_data), sample_step):
            pixel = bytes(view[offset:offset + pixel_size])
            if pixel == previous:
                repeat_pairs += 1
            previous = pixel
            unique.add(pixel)
            samples_seen += 1
            if len(unique) > self.fast_raw_unique_threshold:
                return {
                    "prefer_raw": True,
                    "run_friendly": False,
                    "palette_candidate": False,
                }

        run_ratio = repeat_pairs / max(1, samples_seen - 1)
        palette_candidate = len(unique) <= self.fast_palette_max_colors
        prefer_raw = (not palette_candidate) and run_ratio < self.fast_raw_run_ratio_threshold
        return {
            "prefer_raw": prefer_raw,
            "run_friendly": run_ratio >= self.fast_raw_run_ratio_threshold,
            "palette_candidate": palette_candidate,
        }

    def _split_pixels(self, pixel_data: PixelData, pixel_size: int) -> list[int]:
        usable = len(pixel_data) - (len(pixel_data) % pixel_size)
        if usable <= 0:
            return []

        view = memoryview(pixel_data)
        if pixel_size == 1:
            return list(view[:usable])
        if pixel_size == 2:
            return [(view[offset] << 8) | view[offset + 1] for offset in range(0, usable, 2)]
        if pixel_size == 3:
            return [
                (view[offset] << 16) | (view[offset + 1] << 8) | view[offset + 2]
                for offset in range(0, usable, 3)
            ]
        return [
            int.from_bytes(view[offset:offset + pixel_size], "big")
            for offset in range(0, usable, pixel_size)
        ]

    def _palette_in_order(self, pixels: list[int], limit: int) -> list[int]:
        palette: list[int] = []
        seen: dict[int, int] = {}
        for pixel in pixels:
            if pixel in seen:
                continue
            seen[pixel] = len(palette)
            palette.append(pixel)
            if len(palette) > limit:
                return []
        return palette

    def _encode_plain_rle(self, pixels: list[int], pixel_size: int) -> bytes:
        result = bytearray()
        index = 0
        while index < len(pixels):
            pixel = pixels[index]
            run_length = 1
            while index + run_length < len(pixels) and pixels[index + run_length] == pixel:
                run_length += 1
            result.extend(self._pixel_to_bytes(pixel, pixel_size))
            self._encode_run_length_into(result, run_length)
            index += run_length
        return bytes(result)

    def _encode_palette_rle(self, pixels: list[int], palette: list[int]) -> bytes:
        palette_index = {pixel: idx for idx, pixel in enumerate(palette)}
        result = bytearray()
        index = 0
        while index < len(pixels):
            pixel = pixels[index]
            run_length = 1
            while index + run_length < len(pixels) and pixels[index + run_length] == pixel:
                run_length += 1
            idx = palette_index[pixel]
            if run_length == 1:
                result.append(idx)
            else:
                result.append(idx + 128)
                self._encode_run_length_into(result, run_length)
            index += run_length
        return bytes(result)

    def _encode_run_length(self, run_length: int) -> bytes:
        remaining = max(0, run_length - 1)
        encoded = bytearray()
        while remaining >= 255:
            encoded.append(255)
            remaining -= 255
        encoded.append(remaining)
        return bytes(encoded)

    def _encode_run_length_into(self, result: bytearray, run_length: int) -> None:
        remaining = max(0, run_length - 1)
        while remaining >= 255:
            result.append(255)
            remaining -= 255
        result.append(remaining)

    def _encode_packed_palette(self, pixels: list[int], palette: list[int],
                               width: int, height: int) -> bytes:
        palette_index = {pixel: idx for idx, pixel in enumerate(palette)}
        palette_size = len(palette)
        if palette_size == 2:
            bits_per_index = 1
        elif palette_size <= 4:
            bits_per_index = 2
        else:
            bits_per_index = 4

        result = bytearray()
        pixel_iter = iter(pixels)
        for _ in range(height):
            current_byte = 0
            used_bits = 0
            for _ in range(width):
                idx = palette_index[next(pixel_iter)]
                current_byte = (current_byte << bits_per_index) | idx
                used_bits += bits_per_index
                if used_bits == 8:
                    result.append(current_byte)
                    current_byte = 0
                    used_bits = 0
            if used_bits:
                current_byte <<= (8 - used_bits)
                result.append(current_byte)
        return bytes(result)

    def _pixel_to_bytes(self, pixel: int, pixel_size: int) -> bytes:
        if pixel_size == 1:
            return bytes((pixel & 0xFF,))
        return pixel.to_bytes(pixel_size, "big")


class EncoderManager:
    """
    Manages encoding selection based on client preferences
    and content analysis (Python 3.13 style)
    """

    def __init__(self, enable_tight: bool = True, enable_h264: bool = False,
                 enable_jpeg: bool = True, disable_tight_for_ultravnc: bool = False,
                 enable_copyrect: bool = False, enable_zrle: bool = False):
        self.encoders: dict[int, Encoder] = {
            0: RawEncoder(),
            2: RREEncoder(),
            5: HextileEncoder(),
            6: ZlibEncoder(),
        }

        # Keep experimental/non-compliant encoders opt-in only until their
        # wire-format implementation matches the RFCs we claim to support.
        if enable_copyrect:
            self.encoders[1] = CopyRectEncoder()
        if enable_zrle:
            self.encoders[16] = ZRLEEncoder()

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

        self._disable_tight_for_ultravnc = disable_tight_for_ultravnc

    def get_best_encoder(self, client_encodings: Iterable[int],
                        content_type: str = "default") -> tuple[int, Encoder]:
        """
        Select best encoder in the order preferred by the client.

        Args:
            client_encodings: Ordered encoding preference list from the client
            content_type: Retained for API compatibility; selection is client-first

        Returns:
            (encoding_type, encoder) tuple
        """
        ordered_client_encodings = _unique_encoding_order(client_encodings)

        # Find first available encoder in client-preferred order.
        for enc_type in ordered_client_encodings:
            if enc_type in self.encoders:
                self.logger.debug(
                    "Selected encoding %s from client preference order for content type: %s",
                    enc_type,
                    content_type,
                )
                return enc_type, self.encoders[enc_type]

        # Fallback to raw
        return 0, self.encoders[0]
