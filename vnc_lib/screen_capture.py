"""
Screen Capture Module
Handles screen grabbing and pixel format conversion
"""

import hashlib
import logging
import time
from typing import Tuple, Optional, Dict
from PIL import ImageGrab, Image


class ScreenCapture:
    """Handles screen capture and format conversion"""

    def __init__(self, scale_factor: float = 1.0):
        """
        Initialize screen capture

        Args:
            scale_factor: Scale factor for resizing (1.0 = no scaling)
        """
        self.scale_factor = scale_factor
        self.logger = logging.getLogger(__name__)
        self.last_checksum = None

    def capture(self, pixel_format: Dict) -> Tuple[Optional[bytes], Optional[bytes], int, int]:
        """
        Capture screen and convert to specified pixel format

        Args:
            pixel_format: Client's requested pixel format

        Returns:
            (pixel_data, checksum, width, height)
        """
        try:
            start_time = time.time()

            # Grab screenshot
            screenshot = ImageGrab.grab()
            width, height = screenshot.size

            # Apply scaling if needed
            scaled_width = int(width * self.scale_factor)
            scaled_height = int(height * self.scale_factor)

            if scaled_width < 1 or scaled_height < 1:
                self.logger.warning("Scale factor too small")
                return None, None, 0, 0

            if self.scale_factor != 1.0:
                screenshot = screenshot.resize(
                    (scaled_width, scaled_height),
                    Image.Resampling.BILINEAR
                )
                width, height = scaled_width, scaled_height

            # Convert to requested pixel format
            pixel_data = self._convert_to_pixel_format(screenshot, pixel_format)

            # Calculate checksum for change detection
            checksum = hashlib.md5(pixel_data).digest()

            elapsed = time.time() - start_time
            self.logger.debug(f"Screen capture took {elapsed:.4f}s, size={len(pixel_data)} bytes")

            return pixel_data, checksum, width, height

        except Exception as e:
            self.logger.error(f"Screen capture error: {e}")
            return None, None, 0, 0

    def _convert_to_pixel_format(self, image: Image.Image, pixel_format: Dict) -> bytes:
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

    def _convert_to_32bit_true_color(self, image: Image.Image,
                                     pixel_format: Dict, big_endian: bool) -> bytes:
        """Convert to 32-bit true color format"""
        # Get RGB data
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        pixels = rgb_image.load()

        # Extract shift values
        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']

        # Build pixel data
        data = bytearray(width * height * 4)
        offset = 0

        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]

                # Pack according to shift values
                pixel_value = (r << red_shift) | (g << green_shift) | (b << blue_shift)

                # Write as 32-bit value
                if big_endian:
                    data[offset:offset+4] = pixel_value.to_bytes(4, byteorder='big')
                else:
                    data[offset:offset+4] = pixel_value.to_bytes(4, byteorder='little')

                offset += 4

        return bytes(data)

    def _convert_to_16bit_true_color(self, image: Image.Image,
                                     pixel_format: Dict, big_endian: bool) -> bytes:
        """Convert to 16-bit true color format (e.g., RGB565)"""
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        pixels = rgb_image.load()

        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']
        red_max = pixel_format['red_max']
        green_max = pixel_format['green_max']
        blue_max = pixel_format['blue_max']

        data = bytearray(width * height * 2)
        offset = 0

        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]

                # Scale to max values
                r = (r * red_max) // 255
                g = (g * green_max) // 255
                b = (b * blue_max) // 255

                # Pack according to shift values
                pixel_value = (r << red_shift) | (g << green_shift) | (b << blue_shift)

                # Write as 16-bit value
                if big_endian:
                    data[offset:offset+2] = pixel_value.to_bytes(2, byteorder='big')
                else:
                    data[offset:offset+2] = pixel_value.to_bytes(2, byteorder='little')

                offset += 2

        return bytes(data)

    def _convert_to_8bit_true_color(self, image: Image.Image, pixel_format: Dict) -> bytes:
        """Convert to 8-bit true color format (e.g., RGB332)"""
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        pixels = rgb_image.load()

        red_shift = pixel_format['red_shift']
        green_shift = pixel_format['green_shift']
        blue_shift = pixel_format['blue_shift']
        red_max = pixel_format['red_max']
        green_max = pixel_format['green_max']
        blue_max = pixel_format['blue_max']

        data = bytearray(width * height)
        offset = 0

        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]

                # Scale to max values
                r = (r * red_max) // 255
                g = (g * green_max) // 255
                b = (b * blue_max) // 255

                # Pack according to shift values
                pixel_value = (r << red_shift) | (g << green_shift) | (b << blue_shift)

                data[offset] = pixel_value & 0xFF
                offset += 1

        return bytes(data)

    def has_changed(self, checksum: bytes) -> bool:
        """Check if screen has changed since last capture"""
        if self.last_checksum is None:
            return True
        return checksum != self.last_checksum

    def update_checksum(self, checksum: bytes):
        """Update last checksum"""
        self.last_checksum = checksum
