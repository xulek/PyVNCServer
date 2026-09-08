"""
VNC Server Library - RFC 6143 compliant implementation
"""

from pyvncserver._version import __version__

from .protocol import RFBProtocol
from .auth import VNCAuth, NoAuth
from .vencrypt import VeNCryptServer, VeNCryptResult
from .input_handler import InputHandler
from .screen_capture import ScreenCapture, CaptureResult
from .capture_backends import CaptureFrame, CaptureMetadata, CaptureMoveRect

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

from .exceptions import (
    VNCError, ProtocolError, AuthenticationError, EncodingError,
    ScreenCaptureError, ConnectionError as VNCConnectionError, ConfigurationError,
    VNCExceptionGroup, MultiClientError, ExceptionCollector
)
from .desktop_resize import (
    Screen, DesktopSizeHandler,
    create_single_screen_layout, create_dual_screen_layout
)

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
    ReusableConnectionPool, ConnectionPoolManager, PooledConnection,
    ConnectionMetrics as ConnMetrics
)
AdvancedConnectionPool = ReusableConnectionPool
from .performance_monitor import (
    PerformanceMonitor as PerfMonitor, PerformanceTimer,
    ResourceMonitor, MemoryProfiler, get_global_monitor, time_function
)

try:
    from .types import (
        PixelData, EncodedData, PixelFormat, ClientID
    )
except ImportError:
    pass

__all__ = [
    'RFBProtocol', 'VNCAuth', 'NoAuth', 'VeNCryptServer', 'VeNCryptResult', 'InputHandler',
    'ScreenCapture', 'CaptureResult', 'CaptureFrame', 'CaptureMetadata',
    'CaptureMoveRect',
    'RawEncoder', 'RREEncoder', 'HextileEncoder', 'ZRLEEncoder',
    'CopyRectEncoder', 'EncoderManager',
    'Region', 'TileGrid', 'AdaptiveChangeDetector',
    'CursorData', 'CursorEncoder',
    'ConnectionMetrics', 'ServerMetrics', 'PerformanceMonitor',
    'SlidingWindow', 'format_bytes', 'format_duration',
    'HealthStatus', 'GracefulShutdown', 'HealthChecker',
    'ConnectionPool', 'PerformanceThrottler',
    'VNCError', 'ProtocolError', 'AuthenticationError', 'EncodingError',
    'ScreenCaptureError', 'VNCConnectionError', 'ConfigurationError',
    'VNCExceptionGroup', 'MultiClientError', 'ExceptionCollector',
    'Screen', 'DesktopSizeHandler',
    'create_single_screen_layout', 'create_dual_screen_layout',
    'SessionRecorder', 'SessionPlayer', 'SessionEvent', 'EventType',
    'ClipboardManager', 'ClipboardData', 'ClipboardHistory',
    'sanitize_clipboard_text',
    'PrometheusExporter', 'MetricsRegistry', 'VNCMetricsCollector',
    'StructuredLogger', 'LogContext', 'CorrelationContext',
    'PerformanceLogger', 'AuditLogger', 'configure_logging', 'get_logger',
    'AdvancedConnectionPool', 'ConnectionPoolManager', 'PooledConnection',
    'ConnMetrics',
    'PerfMonitor', 'PerformanceTimer', 'ResourceMonitor', 'MemoryProfiler',
    'get_global_monitor', 'time_function',
]
