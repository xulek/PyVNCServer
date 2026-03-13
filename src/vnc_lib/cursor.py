"""
Cursor handling and encoding for VNC
Implements cursor pseudo-encoding (RFC 6143 Section 7.8.1)
"""

import logging
import struct
from typing import NamedTuple


class CursorData(NamedTuple):
    """Cursor data structure (Python 3.13 style)"""
    width: int
    height: int
    hotspot_x: int
    hotspot_y: int
    pixel_data: bytes  # RGBA pixel data
    bitmask: bytes     # Transparency bitmask


class CursorEncoder:
    """
    Encodes cursor data for VNC transmission
    RFC 6143 Section 7.8.1 - Cursor pseudo-encoding
    """

    # Pseudo-encoding types
    ENCODING_CURSOR = -239
    ENCODING_X_CURSOR = -240
    ENCODING_RICH_CURSOR = -239  # Same as CURSOR

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.last_cursor: CursorData | None = None

    def encode_cursor(self, cursor_data: CursorData,
                     bytes_per_pixel: int = 4) -> tuple[int, int, bytes]:
        """
        Encode cursor as framebuffer update rectangle

        Args:
            cursor_data: Cursor data to encode
            bytes_per_pixel: Bytes per pixel for encoding

        Returns:
            (hotspot_x, hotspot_y, encoded_data) tuple
        """
        # Store last cursor for change detection
        self.last_cursor = cursor_data

        width = cursor_data.width
        height = cursor_data.height

        # Encode pixel data
        encoded_pixels = self._encode_pixels(
            cursor_data.pixel_data, width, height, bytes_per_pixel
        )

        # Encode bitmask (1 bit per pixel, padded to byte boundary)
        encoded_mask = self._encode_bitmask(
            cursor_data.bitmask, width, height
        )

        # Combine pixel data and mask
        encoded_data = encoded_pixels + encoded_mask

        self.logger.debug(
            f"Encoded cursor: {width}x{height}, "
            f"hotspot=({cursor_data.hotspot_x},{cursor_data.hotspot_y}), "
            f"size={len(encoded_data)} bytes"
        )

        return cursor_data.hotspot_x, cursor_data.hotspot_y, encoded_data

    def _encode_pixels(self, pixel_data: bytes, width: int, height: int,
                      bpp: int) -> bytes:
        """
        Encode cursor pixel data

        Args:
            pixel_data: RGBA pixel data
            width: Cursor width
            height: Cursor height
            bpp: Target bytes per pixel

        Returns:
            Encoded pixel data
        """
        if bpp == 4:
            # 32-bit RGBA - use as-is
            return pixel_data
        elif bpp == 3:
            # 24-bit RGB - strip alpha
            result = bytearray()
            for i in range(0, len(pixel_data), 4):
                result.extend(pixel_data[i:i+3])
            return bytes(result)
        elif bpp == 2:
            # 16-bit RGB565
            result = bytearray()
            for i in range(0, len(pixel_data), 4):
                r, g, b = pixel_data[i:i+3]
                # Convert to RGB565
                r5 = (r >> 3) & 0x1F
                g6 = (g >> 2) & 0x3F
                b5 = (b >> 3) & 0x1F
                rgb565 = (r5 << 11) | (g6 << 5) | b5
                result.extend(struct.pack(">H", rgb565))
            return bytes(result)
        else:
            # Unsupported format
            self.logger.warning(f"Unsupported cursor bpp: {bpp}")
            return pixel_data

    def _encode_bitmask(self, bitmask: bytes, width: int, height: int) -> bytes:
        """
        Encode cursor transparency bitmask

        Bitmask format: 1 bit per pixel, rows padded to byte boundary
        1 = opaque, 0 = transparent

        Args:
            bitmask: Input bitmask (1 byte per pixel, 0=transparent, 255=opaque)
            width: Cursor width
            height: Cursor height

        Returns:
            Encoded bitmask
        """
        result = bytearray()

        for y in range(height):
            byte_val = 0
            bit_pos = 7

            for x in range(width):
                pixel_idx = y * width + x

                # Get transparency value
                if pixel_idx < len(bitmask):
                    is_opaque = bitmask[pixel_idx] > 127
                else:
                    is_opaque = False

                if is_opaque:
                    byte_val |= (1 << bit_pos)

                bit_pos -= 1

                # Byte complete or end of row
                if bit_pos < 0 or x == width - 1:
                    result.append(byte_val)
                    byte_val = 0
                    bit_pos = 7

        return bytes(result)

    def has_cursor_changed(self, new_cursor: CursorData) -> bool:
        """Check if cursor has changed since last encoding"""
        if self.last_cursor is None:
            return True

        return (
            self.last_cursor.width != new_cursor.width or
            self.last_cursor.height != new_cursor.height or
            self.last_cursor.hotspot_x != new_cursor.hotspot_x or
            self.last_cursor.hotspot_y != new_cursor.hotspot_y or
            self.last_cursor.pixel_data != new_cursor.pixel_data or
            self.last_cursor.bitmask != new_cursor.bitmask
        )


class SystemCursorCapture:
    """
    Captures system cursor (platform-specific)
    Note: This is a stub implementation - full implementation would
    use platform-specific APIs (Win32, X11, macOS)
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.enabled = False  # Disabled by default

    def capture_cursor(self) -> CursorData | None:
        """
        Capture current system cursor

        Returns:
            CursorData or None if cursor capture not available
        """
        if not self.enabled:
            return None

        # TODO: Implement platform-specific cursor capture
        # - Windows: GetCursorInfo, GetIconInfo, GetDIBits
        # - X11: XFixesGetCursorImage
        # - macOS: CGDisplayCreateImage

        self.logger.debug("Cursor capture not implemented")
        return None

    def create_default_cursor(self) -> CursorData:
        """
        Create a simple default cursor (arrow)

        Returns:
            Default cursor data
        """
        # Simple 16x16 arrow cursor
        width, height = 16, 16
        hotspot_x, hotspot_y = 0, 0

        # Create arrow pattern (simplified)
        pixel_data = bytearray(width * height * 4)
        bitmask = bytearray(width * height)

        # Simple black arrow
        for y in range(height):
            for x in range(width):
                idx = y * width + x
                pixel_idx = idx * 4

                # Arrow shape
                if x <= y and x < 8 and y < 12:
                    # Black pixel
                    pixel_data[pixel_idx:pixel_idx+4] = b'\x00\x00\x00\xFF'
                    bitmask[idx] = 255
                else:
                    # Transparent
                    pixel_data[pixel_idx:pixel_idx+4] = b'\x00\x00\x00\x00'
                    bitmask[idx] = 0

        return CursorData(
            width=width,
            height=height,
            hotspot_x=hotspot_x,
            hotspot_y=hotspot_y,
            pixel_data=bytes(pixel_data),
            bitmask=bytes(bitmask)
        )
