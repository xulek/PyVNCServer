"""Public plugin API for PyVNCServer 4.x."""

from .interfaces import (
    CaptureBackendPlugin,
    CaptureBackendProtocol,
    EncoderProtocol,
    EncodingPlugin,
    SecurityPlugin,
    SecurityPluginResult,
)
from .registry import PluginManager

__all__ = [
    "CaptureBackendPlugin",
    "CaptureBackendProtocol",
    "EncoderProtocol",
    "EncodingPlugin",
    "PluginManager",
    "SecurityPlugin",
    "SecurityPluginResult",
]
