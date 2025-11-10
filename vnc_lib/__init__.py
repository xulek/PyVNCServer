"""
VNC Server Library - RFC 6143 compliant implementation
Enhanced Version 3.0 with Python 3.13 features

New in v3.0:
- Pattern matching (match/case) for message handling
- Generic type parameters (PEP 695)
- Exception groups (PEP 654)
- CopyRect encoding for efficient scrolling
- Desktop resize support (ExtendedDesktopSize)
- Comprehensive type system
- Enhanced metrics with SlidingWindow
"""

__version__ = "3.0.0"

# Core modules
from .protocol import RFBProtocol
from .auth import VNCAuth, NoAuth
from .input_handler import InputHandler
from .screen_capture import ScreenCapture, CaptureResult

# Enhanced v3.0 modules
from .encodings import (
    RawEncoder, RREEncoder, HextileEncoder, ZRLEEncoder,
    CopyRectEncoder, EncoderManager
)
from .change_detector import Region, TileGrid, AdaptiveChangeDetector
from .cursor import CursorData, CursorEncoder
from .metrics import (
    ConnectionMetrics, ServerMetrics, PerformanceMonitor,
    SlidingWindow, format_bytes, format_duration
)
from .server_utils import (
    HealthStatus, GracefulShutdown, HealthChecker,
    ConnectionPool, PerformanceThrottler
)

# Python 3.13 enhancements
from .exceptions import (
    VNCError, ProtocolError, AuthenticationError, EncodingError,
    ScreenCaptureError, ConnectionError, ConfigurationError,
    VNCExceptionGroup, MultiClientError, ExceptionCollector
)
from .desktop_resize import (
    Screen, DesktopSizeHandler,
    create_single_screen_layout, create_dual_screen_layout
)

# Type system (optional import for type checking)
try:
    from .types import (
        PixelData, EncodedData, PixelFormat, ClientID,
        Result, Ok, Err
    )
except ImportError:
    # Types module is optional
    pass

__all__ = [
    # Core
    'RFBProtocol',
    'VNCAuth',
    'NoAuth',
    'InputHandler',
    'ScreenCapture',
    'CaptureResult',

    # Encodings
    'RawEncoder',
    'RREEncoder',
    'HextileEncoder',
    'ZRLEEncoder',
    'CopyRectEncoder',  # New in v3.0
    'EncoderManager',

    # Change Detection
    'Region',
    'TileGrid',
    'AdaptiveChangeDetector',

    # Cursor
    'CursorData',
    'CursorEncoder',

    # Metrics (Enhanced in v3.0)
    'ConnectionMetrics',
    'ServerMetrics',
    'PerformanceMonitor',
    'SlidingWindow',  # New in v3.0
    'format_bytes',
    'format_duration',

    # Server Utils
    'HealthStatus',
    'GracefulShutdown',
    'HealthChecker',
    'ConnectionPool',
    'PerformanceThrottler',

    # Exceptions (New in v3.0)
    'VNCError',
    'ProtocolError',
    'AuthenticationError',
    'EncodingError',
    'ScreenCaptureError',
    'ConnectionError',
    'ConfigurationError',
    'VNCExceptionGroup',
    'MultiClientError',
    'ExceptionCollector',

    # Desktop Resize (New in v3.0)
    'Screen',
    'DesktopSizeHandler',
    'create_single_screen_layout',
    'create_dual_screen_layout',
]
