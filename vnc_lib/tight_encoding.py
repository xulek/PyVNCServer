"""
Tight Encoding Implementation - TightVNC Protocol
Provides 20-100x compression for typical desktop content
Combines multiple compression methods for optimal performance
"""

import struct
import zlib
import logging
from typing import TypeAlias
from enum import IntEnum

# Type aliases
PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes


class TightCompressionControl(IntEnum):
    """Tight encoding compression control bits (TightVNC specification)"""
    BASIC = 0x00        # Basic compression, zlib stream 0, no reset
    FILL = 0x80         # Fill compression (rfbTightFill << 4)
    JPEG = 0x90         # JPEG compression (rfbTightJpeg << 4)
    NO_ZLIB = 0xA0      # Basic, no zlib (rfbTightNoZlib << 4)

    # Filter ids (separate byte after control when bit 6 is set)
    FILTER_COPY = 0x00      # No filter
    FILTER_PALETTE = 0x01   # Palette filter
    FILTER_GRADIENT = 0x02  # Gradient filter


class TightEncoder:
    """
    Tight Encoding - TightVNC Protocol Extension

    Tight encoding is the most bandwidth-efficient encoding for VNC.
    It combines multiple techniques:
    1. Fill compression for solid colors
    2. Palette compression for limited color content
    3. Gradient filter for smooth gradients
    4. Zlib compression for remaining data
    5. JPEG compression for photographic content (Type 21 - separate)

    Compression ratio: 20-100x for typical desktop content
    """

    ENCODING_TYPE = 7

    # Compression streams (0-3, separate zlib streams for better compression)
    STREAM_RAW = 0
    STREAM_FILL = 1
    STREAM_PALETTE = 2
    STREAM_GRADIENT = 3

    # Compression levels
    COMPRESSION_MIN = 1
    COMPRESSION_MAX = 9
    COMPRESSION_DEFAULT = 6

    def __init__(self, compression_level: int = COMPRESSION_DEFAULT):
        """
        Initialize Tight encoder

        Args:
            compression_level: zlib compression level (1-9)
        """
        self.compression_level = max(self.COMPRESSION_MIN,
                                     min(self.COMPRESSION_MAX, compression_level))
        self.logger = logging.getLogger(__name__)

        # Separate persistent zlib compressors for each stream (0..3)
        # Matches LibVNCServer Tight implementation (better compression).
        self.compressors = {
            i: zlib.compressobj(self.compression_level, zlib.DEFLATED, zlib.MAX_WBITS)
            for i in range(4)
        }

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        Encode pixel data using Tight encoding

        Process:
        1. Analyze content type
        2. Choose best compression method
        3. Apply compression
        4. Return encoded data
        """
        if bytes_per_pixel not in (1, 2, 3, 4):
            self.logger.warning(f"Tight: unsupported bpp {bytes_per_pixel}, using raw")
            return self._encode_raw(pixel_data, width, height, bytes_per_pixel)

        # TEMPORARILY DISABLED FOR TESTING: Use only BASIC compression
        # Check for solid color fill (common for backgrounds)
        # if self._is_solid_fill(pixel_data, bytes_per_pixel):
        #     return self._encode_fill(pixel_data, bytes_per_pixel)

        # Check for palette-based content (limited colors)
        # palette = self._extract_palette(pixel_data, bytes_per_pixel, max_colors=256)
        # if palette and len(palette) <= 2:
        #     # Very few colors - use palette encoding
        #     return self._encode_palette(pixel_data, width, height, bytes_per_pixel, palette)

        # For gradient/photo content, use basic compression with optional filter
        # if self._has_smooth_gradient(pixel_data, width, height, bytes_per_pixel):
        #     return self._encode_gradient(pixel_data, width, height, bytes_per_pixel)

        # Default: basic zlib compression (TESTING: using only this now)
        return self._encode_basic(pixel_data, width, height, bytes_per_pixel)

    def _is_solid_fill(self, pixel_data: PixelData, bpp: int,
                       sample_rate: int = 100) -> bool:
        """Check if image is solid color (sample-based for speed)"""
        if len(pixel_data) < bpp:
            return True

        first_pixel = pixel_data[:bpp]
        data_len = len(pixel_data)

        # Sample every Nth pixel for speed
        for i in range(bpp, min(data_len, bpp * sample_rate), bpp):
            if pixel_data[i:i+bpp] != first_pixel:
                return False

        return True

    def _encode_fill(self, pixel_data: PixelData, bpp: int) -> EncodedData:
        """
        Encode solid color fill

        Format:
        - 1 byte: compression control (0x80 = FILL)
        - TPIXEL: pixel value in Tight pixel format (3 bytes for 24-bit true-color)

        TPIXEL is like PIXEL but for 32bpp true-color, only 3 bytes (RGB) are sent,
        omitting the padding/alpha byte.

        This is extremely efficient: 4 bytes for entire screen!
        """
        control = TightCompressionControl.FILL

        # For 32bpp true-color, TPIXEL is 3 bytes (RGB), not 4
        # Extract RGB components (assuming BGRA format)
        if bpp == 4:
            # 32bpp: send only RGB (3 bytes), skip alpha/padding
            pixel_value = pixel_data[:3]  # First 3 bytes = BGR or RGB
        else:
            # For other bpp, use full pixel
            pixel_value = pixel_data[:bpp]

        result = struct.pack("B", control) + pixel_value

        self.logger.debug(f"Tight FILL: {len(pixel_data)} -> {len(result)} bytes "
                         f"({len(pixel_data) / len(result):.1f}x compression)")
        self.logger.debug(f"Fill: control=0x{control:02x}, pixel={pixel_value.hex()}, "
                         f"total_bytes={result.hex()}")

        return result

    def _extract_palette(self, pixel_data: PixelData, bpp: int,
                        max_colors: int = 256) -> list[bytes] | None:
        """
        Extract color palette from image

        Returns palette if colors <= max_colors, else None
        """
        unique_colors: set[bytes] = set()

        for i in range(0, len(pixel_data), bpp):
            pixel = pixel_data[i:i+bpp]
            unique_colors.add(pixel)

            if len(unique_colors) > max_colors:
                return None

        return list(unique_colors)

    def _encode_palette(self, pixel_data: PixelData, width: int, height: int,
                       bpp: int, palette: list[bytes]) -> EncodedData:
        """
        Encode using palette compression

        Format:
        - 1 byte: compression control (basic + zlib, explicit filter)
        - 1 byte: filter id (= 1, palette)
        - 1 byte: palette size - 1
        - palette_size * bpp bytes: palette colors
        - compressed indices

        For 2 colors: uses 1 bit per pixel
        For 3-16 colors: uses 4 bits per pixel
        For 17-256 colors: uses 8 bits per pixel
        """
        num_colors = len(palette)

        if num_colors > 256:
            return self._encode_basic(pixel_data, width, height, bpp)

        # Build palette index map
        palette_map = {color: idx for idx, color in enumerate(palette)}

        # Compression control with explicit PALETTE filter on stream 2.
        # High nibble: (stream_id | rfbTightExplicitFilter) << 4
        # Low nibble: reset bit for this stream so the client
        #             resets its zlib state before decoding.
        stream_id = self.STREAM_PALETTE
        reset_mask = 1 << stream_id
        control_nibble = stream_id | 0x04  # rfbTightExplicitFilter
        control = (control_nibble << 4) | reset_mask

        result = bytearray([control, TightCompressionControl.FILTER_PALETTE, num_colors - 1])

        # Add palette colors
        for color in palette:
            result.extend(color)

        # Encode indices
        if num_colors == 2:
            # 1 bit per pixel (packed into bytes)
            indices = self._pack_indices_1bit(pixel_data, bpp, palette_map, width, height)
        elif num_colors <= 16:
            # 4 bits per pixel
            indices = self._pack_indices_4bit(pixel_data, bpp, palette_map)
        else:
            # 8 bits per pixel
            indices = self._pack_indices_8bit(pixel_data, bpp, palette_map)

        # Compress indices with zlib
        compressed = zlib.compress(indices, self.compression_level)

        # Add compressed length (compact format)
        result.extend(self._encode_compact_length(len(compressed)))
        result.extend(compressed)

        self.logger.debug(f"Tight PALETTE ({num_colors} colors): {len(pixel_data)} -> "
                         f"{len(result)} bytes ({len(pixel_data) / len(result):.1f}x)")

        return bytes(result)

    def _pack_indices_1bit(self, pixel_data: PixelData, bpp: int,
                          palette_map: dict[bytes, int],
                          width: int, height: int) -> bytes:
        """Pack palette indices as 1 bit per pixel (for 2-color palettes)"""
        result = bytearray()

        for y in range(height):
            byte_val = 0
            bit_pos = 7

            for x in range(width):
                offset = (y * width + x) * bpp
                pixel = pixel_data[offset:offset+bpp]
                index = palette_map.get(pixel, 0)

                if index:
                    byte_val |= (1 << bit_pos)

                bit_pos -= 1
                if bit_pos < 0:
                    result.append(byte_val)
                    byte_val = 0
                    bit_pos = 7

            # Flush remaining bits at end of row
            if bit_pos < 7:
                result.append(byte_val)

        return bytes(result)

    def _pack_indices_4bit(self, pixel_data: PixelData, bpp: int,
                          palette_map: dict[bytes, int]) -> bytes:
        """Pack palette indices as 4 bits per pixel (for 3-16 color palettes)"""
        result = bytearray()
        high_nibble = True
        byte_val = 0

        for i in range(0, len(pixel_data), bpp):
            pixel = pixel_data[i:i+bpp]
            index = palette_map.get(pixel, 0)

            if high_nibble:
                byte_val = (index & 0x0F) << 4
                high_nibble = False
            else:
                byte_val |= (index & 0x0F)
                result.append(byte_val)
                high_nibble = True

        # Flush last nibble if needed
        if not high_nibble:
            result.append(byte_val)

        return bytes(result)

    def _pack_indices_8bit(self, pixel_data: PixelData, bpp: int,
                          palette_map: dict[bytes, int]) -> bytes:
        """Pack palette indices as 8 bits per pixel (for 17-256 color palettes)"""
        result = bytearray()

        for i in range(0, len(pixel_data), bpp):
            pixel = pixel_data[i:i+bpp]
            index = palette_map.get(pixel, 0)
            result.append(index & 0xFF)

        return bytes(result)

    def _has_smooth_gradient(self, pixel_data: PixelData, width: int,
                            height: int, bpp: int) -> bool:
        """
        Check if image has smooth gradients (gradient filter helps)

        Gradient filter predicts pixel value from neighbors,
        then encodes the difference (better compression for gradients)
        """
        # Sample-based gradient detection
        if width < 4 or height < 4:
            return False

        # Check a few pixels for smooth transitions
        gradient_count = 0
        sample_count = 0

        for y in range(1, min(height, 20), 2):
            for x in range(1, min(width, 20), 2):
                offset = (y * width + x) * bpp
                left_offset = (y * width + x - 1) * bpp
                top_offset = ((y - 1) * width + x) * bpp

                if offset + bpp <= len(pixel_data):
                    current = pixel_data[offset:offset+bpp]
                    left = pixel_data[left_offset:left_offset+bpp]
                    top = pixel_data[top_offset:top_offset+bpp]

                    # Check if neighbors are similar (gradient)
                    if self._pixels_similar(current, left, threshold=30):
                        gradient_count += 1
                    if self._pixels_similar(current, top, threshold=30):
                        gradient_count += 1

                    sample_count += 2

        return sample_count > 0 and gradient_count / sample_count > 0.5

    def _pixels_similar(self, p1: bytes, p2: bytes, threshold: int) -> bool:
        """Check if two pixels are similar (within threshold)"""
        if len(p1) != len(p2):
            return False

        total_diff = sum(abs(a - b) for a, b in zip(p1, p2))
        return total_diff <= threshold

    def _encode_gradient(self, pixel_data: PixelData, width: int,
                        height: int, bpp: int) -> EncodedData:
        """
        Encode with gradient filter

        Gradient filter: predict pixel from neighbors, encode difference
        Works well for smooth gradients and photos
        """
        # Compression control with explicit GRADIENT filter on stream 3.
        stream_id = self.STREAM_GRADIENT
        reset_mask = 1 << stream_id
        control_nibble = stream_id | 0x04  # rfbTightExplicitFilter
        control = (control_nibble << 4) | reset_mask

        # Apply gradient filter
        filtered = self._apply_gradient_filter(pixel_data, width, height, bpp)

        # Compress filtered data
        compressed = zlib.compress(filtered, self.compression_level)

        # Build result
        result = bytearray([control, TightCompressionControl.FILTER_GRADIENT])
        result.extend(self._encode_compact_length(len(compressed)))
        result.extend(compressed)

        self.logger.debug(f"Tight GRADIENT: {len(pixel_data)} -> {len(result)} bytes "
                         f"({len(pixel_data) / len(result):.1f}x)")

        return bytes(result)

    def _apply_gradient_filter(self, pixel_data: PixelData, width: int,
                              height: int, bpp: int) -> bytes:
        """
        Apply gradient filter to pixel data

        For each pixel: encode difference from predicted value
        Prediction = left + top - top_left (simple gradient predictor)
        """
        result = bytearray(len(pixel_data))

        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * bpp
                current = pixel_data[offset:offset+bpp]

                if x == 0 and y == 0:
                    # First pixel - no prediction
                    result[offset:offset+bpp] = current
                elif x == 0:
                    # First column - predict from top
                    top_offset = ((y - 1) * width) * bpp
                    top = pixel_data[top_offset:top_offset+bpp]
                    diff = bytes((c - t) & 0xFF for c, t in zip(current, top))
                    result[offset:offset+bpp] = diff
                elif y == 0:
                    # First row - predict from left
                    left_offset = (y * width + x - 1) * bpp
                    left = pixel_data[left_offset:left_offset+bpp]
                    diff = bytes((c - l) & 0xFF for c, l in zip(current, left))
                    result[offset:offset+bpp] = diff
                else:
                    # General case: gradient prediction
                    left_offset = (y * width + x - 1) * bpp
                    top_offset = ((y - 1) * width + x) * bpp
                    topleft_offset = ((y - 1) * width + x - 1) * bpp

                    left = pixel_data[left_offset:left_offset+bpp]
                    top = pixel_data[top_offset:top_offset+bpp]
                    topleft = pixel_data[topleft_offset:topleft_offset+bpp]

                    # Prediction: left + top - topleft
                    predicted = bytes((l + t - tl) & 0xFF
                                     for l, t, tl in zip(left, top, topleft))
                    diff = bytes((c - p) & 0xFF for c, p in zip(current, predicted))
                    result[offset:offset+bpp] = diff

        return bytes(result)

    def _encode_basic(self, pixel_data: PixelData, width: int,
                     height: int, bpp: int) -> EncodedData:
        """
        Basic Tight encoding with zlib compression

        Format (TightVNC specification):
        For basic compression with zlib (no explicit filter):
        - 1 byte: compression control
            bits 0-3: 0 (no stream reset)
            bits 4-7: stream id and flags (0 for stream 0, no filter)
        - 1-3 bytes: compact length of compressed data
        - N bytes: zlib-compressed pixel data from persistent stream
        """
        # Convert to Tight pixel format (TPIXEL).
        # For 32bpp, depth 24, Tight always uses 3 bytes per pixel (R,G,B).
        # ScreenCapture returns 4 bytes per pixel (e.g. RGBX), so drop padding.
        if bpp == 4:
            num_pixels = width * height
            src = memoryview(pixel_data)
            rgb_buf = bytearray(num_pixels * 3)
            rgb_view = memoryview(rgb_buf)
            # Copy R, G, B channels; ignore 4th byte (padding/alpha)
            rgb_view[0::3] = src[0::4]
            rgb_view[1::3] = src[1::4]
            rgb_view[2::3] = src[2::4]
            tight_bytes = bytes(rgb_buf)
        else:
            tight_bytes = pixel_data

        # Use persistent zlib stream 0 (LibVNCServer-style).
        stream_id = self.STREAM_RAW
        control = 0x00  # stream 0, basic, no explicit filter, no reset bits

        compressor = self.compressors[stream_id]
        compressed = compressor.compress(tight_bytes)
        compressed += compressor.flush(zlib.Z_SYNC_FLUSH)

        # Build result with compact length
        result = bytearray([control])
        result.extend(self._encode_compact_length(len(compressed)))
        result.extend(compressed)

        compression_ratio = len(tight_bytes) / len(result) if len(result) > 0 else 0
        self.logger.info(f"Tight BASIC: {len(pixel_data)} -> {len(result)} bytes "
                        f"({compression_ratio:.1f}x), "
                        f"control=0x{control:02x}, stream={stream_id}, "
                        f"compressed_len={len(compressed)}")
        self.logger.debug(f"First 32 bytes: {result[:32].hex()}")

        return bytes(result)

    def _encode_raw(self, pixel_data: PixelData, width: int,
                   height: int, bpp: int) -> EncodedData:
        """
        Fallback to raw encoding (no compression).

        Uses Tight "basic, no zlib" compression type (rfbTightNoZlib).
        Pixel data follows immediately after the control byte, without
        a compact-length prefix.
        """
        control = TightCompressionControl.NO_ZLIB
        return bytes([control]) + pixel_data

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

    def reset_compressors(self):
        """Reset zlib compressors (for new client or stream reset)"""
        self.compressors = {
            i: zlib.compressobj(self.compression_level, zlib.DEFLATED, zlib.MAX_WBITS)
            for i in range(4)
        }
        self.logger.debug("Tight encoder compressors reset")
