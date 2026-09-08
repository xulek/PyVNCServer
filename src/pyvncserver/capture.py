"""Public capture API.

These names are stable for 4.x. The implementation may move internally without
requiring embedders to import private modules.
"""

from ._core.capture_backends import (
    BaseCaptureBackend,
    CaptureBackendCapabilities,
    CaptureFrame,
    CaptureMetadata,
    CaptureMoveRect,
    DXCamCaptureBackend,
    MSSCaptureBackend,
    PILCaptureBackend,
)
from ._core.screen_capture import CaptureResult, ScreenCapture

__all__ = [
    "BaseCaptureBackend",
    "CaptureBackendCapabilities",
    "CaptureFrame",
    "CaptureMetadata",
    "CaptureMoveRect",
    "CaptureResult",
    "DXCamCaptureBackend",
    "MSSCaptureBackend",
    "PILCaptureBackend",
    "ScreenCapture",
]
