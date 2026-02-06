"""
VNC Server Library - RFC 6143 compliant implementation
Enhanced Version 3.1 with Python 3.13 features

New in v3.1:
- Session recording and playback for audit trails
- Clipboard synchronization support
- Prometheus metrics HTTP endpoint
- Structured logging with context
- Advanced connection pooling
- Performance monitoring and profiling
- Enhanced exception handling

New in v3.0:
- Pattern matching (match/case) for message handling
- Generic type parameters (PEP 695)
- Exception groups (PEP 654)
- CopyRect encoding for efficient scrolling
- Desktop resize support (ExtendedDesktopSize)
- Comprehensive type system
- Enhanced metrics with SlidingWindow
"""

__version__ = "3.1.0"

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
    ConnectionPool, PerformanceThrottler,
    NetworkProfile, detect_network_profile
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

# v3.1 New Features
from .session_recorder import (
    SessionRecorder, SessionPlayer, SessionEvent, EventType
)
from .clipboard import (
    ClipboardManager, ClipboardData, ClipboardHistory,
    sanitize_clipboard_text
)
from .prometheus_exporter import (
    PrometheusExporter, MetricsRegistry, VNCMetricsCollector
)
from .structured_logging import (
    StructuredLogger, LogContext, CorrelationContext,
    PerformanceLogger, AuditLogger, configure_logging, get_logger
)
from .connection_pool import (
    ConnectionPool as AdvancedConnectionPool,
    ConnectionPoolManager, PooledConnection, ConnectionMetrics as ConnMetrics
)
from .performance_monitor import (
    PerformanceMonitor as PerfMonitor, PerformanceTimer,
    ResourceMonitor, MemoryProfiler, get_global_monitor, time_function
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

    # v3.1 New Features
    # Session Recording
    'SessionRecorder',
    'SessionPlayer',
    'SessionEvent',
    'EventType',

    # Clipboard
    'ClipboardManager',
    'ClipboardData',
    'ClipboardHistory',
    'sanitize_clipboard_text',

    # Prometheus Metrics
    'PrometheusExporter',
    'MetricsRegistry',
    'VNCMetricsCollector',

    # Structured Logging
    'StructuredLogger',
    'LogContext',
    'CorrelationContext',
    'PerformanceLogger',
    'AuditLogger',
    'configure_logging',
    'get_logger',

    # Advanced Connection Pooling
    'AdvancedConnectionPool',
    'ConnectionPoolManager',
    'PooledConnection',
    'ConnMetrics',

    # Performance Monitoring
    'PerfMonitor',
    'PerformanceTimer',
    'ResourceMonitor',
    'MemoryProfiler',
    'get_global_monitor',
    'time_function',
]
