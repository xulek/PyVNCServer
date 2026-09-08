"""Public exception hierarchy."""

from ._core.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    EncodingError,
    ExceptionCollector,
    MultiClientError,
    ProtocolError,
    ScreenCaptureError,
    VNCError,
    VNCExceptionGroup,
    categorize_exceptions,
)

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "ConnectionError",
    "EncodingError",
    "ExceptionCollector",
    "MultiClientError",
    "ProtocolError",
    "ScreenCaptureError",
    "VNCError",
    "VNCExceptionGroup",
    "categorize_exceptions",
]
