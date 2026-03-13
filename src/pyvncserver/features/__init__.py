"""Optional feature layer."""

from .clipboard import ClipboardData, ClipboardHistory, ClipboardManager, sanitize_clipboard_text
from .recording import EventType, SessionEvent, SessionPlayer, SessionRecorder
from .websocket import WebSocketVNCAdapter, WebSocketWrapper, is_websocket_request

__all__ = [
    "ClipboardData",
    "ClipboardHistory",
    "ClipboardManager",
    "EventType",
    "SessionEvent",
    "SessionPlayer",
    "SessionRecorder",
    "WebSocketVNCAdapter",
    "WebSocketWrapper",
    "is_websocket_request",
    "sanitize_clipboard_text",
]

