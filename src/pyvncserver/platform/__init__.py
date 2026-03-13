"""OS/platform integration layer."""

from .capture import CaptureResult, ScreenCapture
from .cursor import CursorData, CursorEncoder, SystemCursorCapture
from .desktop import DesktopSizeHandler, Screen, create_dual_screen_layout, create_single_screen_layout
from .input import InputHandler

__all__ = [
    "CaptureResult",
    "CursorData",
    "CursorEncoder",
    "DesktopSizeHandler",
    "InputHandler",
    "Screen",
    "ScreenCapture",
    "SystemCursorCapture",
    "create_dual_screen_layout",
    "create_single_screen_layout",
]

