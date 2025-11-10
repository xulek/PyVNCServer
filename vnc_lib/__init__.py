"""
VNC Server Library - RFC 6143 compliant implementation
Enhanced Version 3.0 with Python 3.13 features
"""

__version__ = "3.0.0"

# Core modules
from .protocol import RFBProtocol
from .auth import VNCAuth, NoAuth
from .input_handler import InputHandler
from .screen_capture import ScreenCapture, CaptureResult

# Enhanced v3.0 modules
from .encodings import (
    RawEncoder, RREEncoder, HextileEncoder, ZRLEEncoder, EncoderManager
)
from .change_detector import Region, TileGrid, AdaptiveChangeDetector
from .cursor import CursorData, CursorEncoder
from .metrics import (
    ConnectionMetrics, ServerMetrics, PerformanceMonitor,
    format_bytes, format_duration
)
from .server_utils import (
    HealthStatus, GracefulShutdown, HealthChecker,
    ConnectionPool, PerformanceThrottler
)

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
    'EncoderManager',

    # Change Detection
    'Region',
    'TileGrid',
    'AdaptiveChangeDetector',

    # Cursor
    'CursorData',
    'CursorEncoder',

    # Metrics
    'ConnectionMetrics',
    'ServerMetrics',
    'PerformanceMonitor',
    'format_bytes',
    'format_duration',

    # Server Utils
    'HealthStatus',
    'GracefulShutdown',
    'HealthChecker',
    'ConnectionPool',
    'PerformanceThrottler',
]
