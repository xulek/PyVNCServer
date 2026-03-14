"""
Capture backend abstractions and metadata hints.

This module does not implement full DXGI dirty/move rect harvesting yet.
It provides a stable interface so the server runtime can consume backend-
supplied metadata as soon as a Windows backend starts exposing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Rectangle = tuple[int, int, int, int]


@dataclass(slots=True)
class CaptureMoveRect:
    """A backend-reported move/copy rectangle."""

    src_x: int
    src_y: int
    dst_x: int
    dst_y: int
    width: int
    height: int


@dataclass(slots=True)
class CaptureMetadata:
    """Optional backend hints for incremental framebuffer updates."""

    backend_name: str
    dirty_regions: list[Rectangle] | None = None
    move_rects: list[CaptureMoveRect] = field(default_factory=list)
    supports_dirty_regions: bool = False
    supports_move_rects: bool = False


@dataclass(slots=True)
class CaptureFrame:
    """Full capture result with backend metadata."""

    result: Any
    metadata: CaptureMetadata


@dataclass(slots=True)
class CaptureBackendCapabilities:
    """Static capture backend capabilities."""

    name: str
    supports_bgra: bool
    supports_rgb: bool
    supports_pil_image: bool
    supports_dirty_regions: bool = False
    supports_move_rects: bool = False


class BaseCaptureBackend:
    """Small backend adapter that operates against a ScreenCapture owner."""

    name = "unknown"
    capabilities = CaptureBackendCapabilities(
        name="unknown",
        supports_bgra=False,
        supports_rgb=False,
        supports_pil_image=False,
    )

    def __init__(self, owner: Any):
        self.owner = owner

    def is_available(self) -> bool:
        return False

    def healthcheck(self) -> bool:
        """Return whether the backend is usable right now."""
        return self.is_available()

    def grab_bgra(self) -> tuple[bytes | None, int, int]:
        return None, 0, 0

    def grab_rgb(self) -> tuple[bytes | None, int, int]:
        return None, 0, 0

    def grab_image(self) -> Any:
        return None

    def build_metadata(self, width: int, height: int) -> CaptureMetadata:
        return CaptureMetadata(
            backend_name=self.name,
            dirty_regions=None,
            move_rects=[],
            supports_dirty_regions=self.capabilities.supports_dirty_regions,
            supports_move_rects=self.capabilities.supports_move_rects,
        )


class MSSCaptureBackend(BaseCaptureBackend):
    name = "mss"
    capabilities = CaptureBackendCapabilities(
        name="mss",
        supports_bgra=True,
        supports_rgb=True,
        supports_pil_image=False,
    )

    def is_available(self) -> bool:
        return bool(getattr(self.owner, "_mss_available", False))

    def healthcheck(self) -> bool:
        try:
            return self.is_available() and self.owner._get_mss_session() is not None
        except Exception:
            return False

    def grab_bgra(self) -> tuple[bytes | None, int, int]:
        sct = self.owner._get_mss_session()
        if sct is None:
            return None, 0, 0
        monitor = sct.monitors[self.owner.monitor] if self.owner.monitor < len(sct.monitors) else sct.monitors[0]
        sct_img = sct.grab(monitor)
        raw = sct_img.raw
        return (raw if isinstance(raw, bytes) else bytes(raw)), int(sct_img.width), int(sct_img.height)

    def grab_rgb(self) -> tuple[bytes | None, int, int]:
        bgra_bytes, width, height = self.grab_bgra()
        if bgra_bytes is None:
            return None, 0, 0

        num_pixels = width * height
        rgb_size = num_pixels * 3
        if self.owner._rgb_buffer is None or len(self.owner._rgb_buffer) != rgb_size:
            self.owner._rgb_buffer = bytearray(rgb_size)

        bgra_view = memoryview(bgra_bytes)
        rgb_view = memoryview(self.owner._rgb_buffer)
        rgb_view[0::3] = bgra_view[2::4]
        rgb_view[1::3] = bgra_view[1::4]
        rgb_view[2::3] = bgra_view[0::4]
        return bytes(self.owner._rgb_buffer), width, height


class PILCaptureBackend(BaseCaptureBackend):
    name = "pil"
    capabilities = CaptureBackendCapabilities(
        name="pil",
        supports_bgra=False,
        supports_rgb=True,
        supports_pil_image=True,
    )

    def is_available(self) -> bool:
        return bool(getattr(self.owner, "_pil_available", False))

    def healthcheck(self) -> bool:
        return self.is_available() and getattr(self.owner, "_ImageGrab", None) is not None

    def grab_rgb(self) -> tuple[bytes | None, int, int]:
        screenshot = self.grab_image()
        if screenshot is None:
            return None, 0, 0
        width, height = screenshot.size
        return screenshot.convert("RGB").tobytes(), int(width), int(height)

    def grab_image(self) -> Any:
        image_grab = getattr(self.owner, "_ImageGrab", None)
        if image_grab is None:
            return None
        return image_grab.grab(all_screens=(self.owner.monitor == 0))


class DXCamCaptureBackend(BaseCaptureBackend):
    name = "dxcam"
    capabilities = CaptureBackendCapabilities(
        name="dxcam",
        supports_bgra=True,
        supports_rgb=True,
        supports_pil_image=False,
        # The runtime is now ready for these metadata hints, but dxcam does not
        # provide them in this implementation yet.
        supports_dirty_regions=False,
        supports_move_rects=False,
    )

    def is_available(self) -> bool:
        return bool(getattr(self.owner, "_dxcam_available", False))

    def healthcheck(self) -> bool:
        try:
            return self.is_available() and self.owner._get_dxcam_session() is not None
        except Exception:
            return False

    def grab_bgra(self) -> tuple[bytes | None, int, int]:
        frame_bytes, width, height, channels, color_hint = self.owner._grab_dxcam_frame()
        if frame_bytes is None:
            return None, 0, 0
        bgra = self.owner._dxcam_frame_to_bgra(
            frame_bytes, width, height, channels, color_hint
        )
        if bgra is None:
            return None, 0, 0
        return bgra, width, height

    def grab_rgb(self) -> tuple[bytes | None, int, int]:
        frame_bytes, width, height, channels, color_hint = self.owner._grab_dxcam_frame()
        if frame_bytes is None:
            return None, 0, 0
        rgb = self.owner._dxcam_frame_to_rgb(
            frame_bytes, width, height, channels, color_hint
        )
        if rgb is None:
            return None, 0, 0
        return rgb, width, height
