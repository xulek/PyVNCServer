"""
Cursor handling and encoding for VNC
Implements cursor pseudo-encoding (RFC 6143 Section 7.8.1)
"""

import ctypes
import logging
import os
import struct
from ctypes import wintypes
from typing import NamedTuple


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    CURSOR_SHOWING = 0x00000001
    DIB_RGB_COLORS = 0
    BI_RGB = 0
    DI_NORMAL = 0x0003
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77

    class CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hCursor", wintypes.HANDLE),
            ("ptScreenPos", wintypes.POINT),
        ]

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    class BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", ctypes.c_long),
            ("bmWidth", ctypes.c_long),
            ("bmHeight", ctypes.c_long),
            ("bmWidthBytes", ctypes.c_long),
            ("bmPlanes", ctypes.c_ushort),
            ("bmBitsPixel", ctypes.c_ushort),
            ("bmBits", ctypes.c_void_p),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class RGBQUAD(ctypes.Structure):
        _fields_ = [
            ("rgbBlue", ctypes.c_ubyte),
            ("rgbGreen", ctypes.c_ubyte),
            ("rgbRed", ctypes.c_ubyte),
            ("rgbReserved", ctypes.c_ubyte),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", RGBQUAD * 1),
        ]

    user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
    user32.GetCursorInfo.restype = wintypes.BOOL
    user32.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL
    user32.DrawIconEx.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.HBRUSH,
        wintypes.UINT,
    ]
    user32.DrawIconEx.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int


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

    def __init__(self, scale_factor: float = 1.0, monitor: int = 0):
        self.logger = logging.getLogger(__name__)
        self.scale_factor = scale_factor
        self.monitor = monitor
        self.enabled = os.name == "nt"

    def capture_cursor(self) -> CursorData | None:
        """
        Capture current system cursor

        Returns:
            CursorData or None if cursor capture not available
        """
        if not self.enabled:
            return None

        try:
            cursor = self._capture_cursor_windows()
            if cursor is None:
                return None
            if self.scale_factor != 1.0:
                cursor = self._scale_cursor_data(cursor)
            return cursor
        except Exception as exc:
            self.logger.debug("Cursor capture failed: %s", exc)
            return None

    def get_pointer_position(self) -> tuple[int, int] | None:
        """Return current pointer position in framebuffer coordinates."""
        if not self.enabled:
            return None
        try:
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return None
            origin_x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            origin_y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            x = point.x - origin_x
            y = point.y - origin_y
            if self.scale_factor != 1.0:
                x = int(round(x * self.scale_factor))
                y = int(round(y * self.scale_factor))
            return x, y
        except Exception as exc:
            self.logger.debug("Pointer position capture failed: %s", exc)
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

    def _capture_cursor_windows(self) -> CursorData | None:
        cursor_info = CURSORINFO()
        cursor_info.cbSize = ctypes.sizeof(CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(cursor_info)):
            return None
        if not (cursor_info.flags & CURSOR_SHOWING):
            return None

        icon_info = ICONINFO()
        if not user32.GetIconInfo(cursor_info.hCursor, ctypes.byref(icon_info)):
            return None

        try:
            if icon_info.hbmColor:
                width, height = self._get_bitmap_dimensions(icon_info.hbmColor)
                rgba, bitmask = self._capture_color_cursor(cursor_info.hCursor, icon_info, width, height)
            else:
                mask_width, mask_height = self._get_bitmap_dimensions(icon_info.hbmMask)
                width = mask_width
                height = max(1, mask_height // 2)
                rgba, bitmask = self._capture_monochrome_cursor(icon_info, width, height)

            if not rgba or width <= 0 or height <= 0:
                return None

            return CursorData(
                width=width,
                height=height,
                hotspot_x=int(icon_info.xHotspot),
                hotspot_y=int(icon_info.yHotspot),
                pixel_data=rgba,
                bitmask=bitmask,
            )
        finally:
            if icon_info.hbmColor:
                gdi32.DeleteObject(icon_info.hbmColor)
            if icon_info.hbmMask:
                gdi32.DeleteObject(icon_info.hbmMask)

    def _capture_color_cursor(
        self, hcursor, icon_info: ICONINFO, width: int, height: int
    ) -> tuple[bytes, bytes]:
        bgra = self._draw_icon_to_bgra(hcursor, width, height)
        if bgra is None:
            return b"", b""

        rgba = bytearray(width * height * 4)
        bitmask = bytearray(width * height)
        any_alpha = False
        for idx in range(width * height):
            src = idx * 4
            b = bgra[src]
            g = bgra[src + 1]
            r = bgra[src + 2]
            a = bgra[src + 3]
            any_alpha = any_alpha or a != 0
            rgba[src:src + 4] = bytes((r, g, b, a))
            bitmask[idx] = 255 if a > 0 else 0

        if any_alpha:
            return bytes(rgba), bytes(bitmask)

        mask_plane = self._extract_mask_plane(icon_info.hbmMask, width, height)
        if mask_plane is None:
            for idx in range(width * height):
                src = idx * 4
                opaque = any(rgba[src:src + 3])
                rgba[src + 3] = 255 if opaque else 0
                bitmask[idx] = 255 if opaque else 0
            return bytes(rgba), bytes(bitmask)

        for idx, mask_bit in enumerate(mask_plane):
            opaque = not mask_bit
            rgba[idx * 4 + 3] = 255 if opaque else 0
            bitmask[idx] = 255 if opaque else 0

        return bytes(rgba), bytes(bitmask)

    def _capture_monochrome_cursor(
        self, icon_info: ICONINFO, width: int, height: int
    ) -> tuple[bytes, bytes]:
        mask_plane = self._extract_mask_plane(icon_info.hbmMask, width, height * 2)
        if mask_plane is None:
            default_cursor = self.create_default_cursor()
            return default_cursor.pixel_data, default_cursor.bitmask

        rgba = bytearray(width * height * 4)
        bitmask = bytearray(width * height)
        row_pixels = width
        for idx in range(width * height):
            and_bit = mask_plane[idx]
            xor_bit = mask_plane[idx + (height * row_pixels)]
            pixel_offset = idx * 4

            if and_bit and not xor_bit:
                rgba[pixel_offset:pixel_offset + 4] = b"\x00\x00\x00\x00"
                bitmask[idx] = 0
            elif not and_bit and not xor_bit:
                rgba[pixel_offset:pixel_offset + 4] = b"\x00\x00\x00\xFF"
                bitmask[idx] = 255
            elif not and_bit and xor_bit:
                rgba[pixel_offset:pixel_offset + 4] = b"\xFF\xFF\xFF\xFF"
                bitmask[idx] = 255
            else:
                rgba[pixel_offset:pixel_offset + 4] = b"\x00\x00\x00\xFF"
                bitmask[idx] = 255

        return bytes(rgba), bytes(bitmask)

    def _get_bitmap_dimensions(self, hbitmap) -> tuple[int, int]:
        bitmap = BITMAP()
        result = gdi32.GetObjectW(hbitmap, ctypes.sizeof(BITMAP), ctypes.byref(bitmap))
        if result == 0:
            raise RuntimeError("GetObjectW failed for cursor bitmap")
        return int(bitmap.bmWidth), int(bitmap.bmHeight)

    def _draw_icon_to_bgra(self, hcursor, width: int, height: int) -> bytes | None:
        screen_dc = user32.GetDC(None)
        if not screen_dc:
            return None

        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        dib = None
        old_obj = None
        bits = ctypes.c_void_p()
        try:
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB
            dib = gdi32.CreateDIBSection(
                screen_dc,
                ctypes.byref(bmi),
                DIB_RGB_COLORS,
                ctypes.byref(bits),
                None,
                0,
            )
            if not dib or not bits.value:
                return None

            old_obj = gdi32.SelectObject(mem_dc, dib)
            ctypes.memset(bits.value, 0, width * height * 4)
            if not user32.DrawIconEx(mem_dc, 0, 0, hcursor, width, height, 0, None, DI_NORMAL):
                return None

            return ctypes.string_at(bits.value, width * height * 4)
        finally:
            if old_obj:
                gdi32.SelectObject(mem_dc, old_obj)
            if dib:
                gdi32.DeleteObject(dib)
            if mem_dc:
                gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, screen_dc)

    def _extract_mask_plane(self, hbitmap, width: int, height: int) -> list[int] | None:
        if not hbitmap or width <= 0 or height <= 0:
            return None

        screen_dc = user32.GetDC(None)
        try:
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 1
            bmi.bmiHeader.biCompression = BI_RGB

            stride = ((width + 31) // 32) * 4
            buffer = ctypes.create_string_buffer(stride * height)
            rows = gdi32.GetDIBits(
                screen_dc,
                hbitmap,
                0,
                height,
                buffer,
                ctypes.byref(bmi),
                DIB_RGB_COLORS,
            )
            if rows == 0:
                return None

            raw = buffer.raw
            plane: list[int] = []
            for y in range(height):
                row_offset = (height - 1 - y) * stride
                for x in range(width):
                    byte_val = raw[row_offset + (x // 8)]
                    bit = (byte_val >> (7 - (x % 8))) & 0x01
                    plane.append(bit)
            return plane
        finally:
            user32.ReleaseDC(None, screen_dc)

    def _scale_cursor_data(self, cursor_data: CursorData) -> CursorData:
        if self.scale_factor == 1.0:
            return cursor_data

        new_width = max(1, int(round(cursor_data.width * self.scale_factor)))
        new_height = max(1, int(round(cursor_data.height * self.scale_factor)))
        scaled_pixels = bytearray(new_width * new_height * 4)
        scaled_mask = bytearray(new_width * new_height)

        for y in range(new_height):
            src_y = min(cursor_data.height - 1, int(y / self.scale_factor))
            for x in range(new_width):
                src_x = min(cursor_data.width - 1, int(x / self.scale_factor))
                src_idx = src_y * cursor_data.width + src_x
                dst_idx = y * new_width + x
                scaled_pixels[dst_idx * 4:dst_idx * 4 + 4] = (
                    cursor_data.pixel_data[src_idx * 4:src_idx * 4 + 4]
                )
                scaled_mask[dst_idx] = cursor_data.bitmask[src_idx]

        return CursorData(
            width=new_width,
            height=new_height,
            hotspot_x=max(0, min(new_width - 1, int(round(cursor_data.hotspot_x * self.scale_factor)))),
            hotspot_y=max(0, min(new_height - 1, int(round(cursor_data.hotspot_y * self.scale_factor)))),
            pixel_data=bytes(scaled_pixels),
            bitmask=bytes(scaled_mask),
        )
