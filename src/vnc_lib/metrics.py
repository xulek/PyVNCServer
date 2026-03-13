"""
Performance metrics and monitoring
Tracks server performance and statistics
Python 3.13 enhanced with generic type parameters
"""

import time
import logging
import threading
from dataclasses import dataclass, field
from collections import deque
from typing import ClassVar, TypeAlias, Generic, TypeVar

# Type aliases (Python 3.12+ would use 'type' statement)
Numeric: TypeAlias = int | float
Timestamp: TypeAlias = float

# Generic type variable
T = TypeVar('T', int, float)


class SlidingWindow(Generic[T]):
    """
    Generic sliding window for tracking numeric values
    Uses generic type parameter (compatible with Python 3.9+)

    Example:
        fps_window: SlidingWindow[float] = SlidingWindow(maxlen=100)
        fps_window.add(60.0)
        avg = fps_window.average()
    """

    def __init__(self, maxlen: int = 100):
        """
        Initialize sliding window

        Args:
            maxlen: Maximum number of values to store
        """
        self.window: deque[T] = deque(maxlen=maxlen)
        self.maxlen = maxlen

    def add(self, value: T) -> None:
        """Add a value to the window"""
        self.window.append(value)

    def clear(self) -> None:
        """Clear all values from the window"""
        self.window.clear()

    def average(self) -> float:
        """Calculate average of all values in window"""
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)  # type: ignore

    def min(self) -> T | None:
        """Get minimum value in window"""
        return min(self.window) if self.window else None

    def max(self) -> T | None:
        """Get maximum value in window"""
        return max(self.window) if self.window else None

    def median(self) -> float:
        """Calculate median of values in window"""
        if not self.window:
            return 0.0
        sorted_values = sorted(self.window)
        n = len(sorted_values)
        if n % 2 == 0:
            return (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2.0
        return float(sorted_values[n//2])

    def percentile(self, p: float) -> float:
        """
        Calculate percentile (0-100) of values in window

        Args:
            p: Percentile to calculate (0-100)
        """
        if not self.window:
            return 0.0
        sorted_values = sorted(self.window)
        k = (len(sorted_values) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c >= len(sorted_values):
            return float(sorted_values[-1])
        return float(sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f]))

    def __len__(self) -> int:
        """Get number of values in window"""
        return len(self.window)

    def __bool__(self) -> bool:
        """Check if window has any values"""
        return bool(self.window)


@dataclass
class ConnectionMetrics:
    """Metrics for a single client connection (Python 3.13 dataclass)"""

    client_id: str
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Frame statistics
    frames_sent: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0

    # Encoding statistics
    encoding_times: deque[float] = field(default_factory=lambda: deque(maxlen=100))
    compression_ratios: deque[float] = field(default_factory=lambda: deque(maxlen=100))

    # Input events
    key_events: int = 0
    pointer_events: int = 0

    # Errors
    error_count: int = 0

    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = time.time()

    def record_frame(self, bytes_sent: int, encoding_time: float,
                    original_size: int):
        """Record frame statistics"""
        self.frames_sent += 1
        self.bytes_sent += bytes_sent
        self.encoding_times.append(encoding_time)

        if original_size > 0:
            compression_ratio = bytes_sent / original_size
            self.compression_ratios.append(compression_ratio)

        self.update_activity()

    def record_input(self, event_type: str):
        """Record input event"""
        if event_type == 'key':
            self.key_events += 1
        elif event_type == 'pointer':
            self.pointer_events += 1
        self.update_activity()

    def record_error(self):
        """Record error"""
        self.error_count += 1

    @property
    def avg_encoding_time(self) -> float:
        """Average encoding time in seconds"""
        if not self.encoding_times:
            return 0.0
        return sum(self.encoding_times) / len(self.encoding_times)

    @property
    def avg_compression_ratio(self) -> float:
        """Average compression ratio"""
        if not self.compression_ratios:
            return 1.0
        return sum(self.compression_ratios) / len(self.compression_ratios)

    @property
    def fps(self) -> float:
        """Frames per second (last 100 frames)"""
        if len(self.encoding_times) < 2:
            return 0.0

        time_window = len(self.encoding_times) * self.avg_encoding_time
        if time_window > 0:
            return len(self.encoding_times) / time_window
        return 0.0

    @property
    def uptime_seconds(self) -> float:
        """Connection uptime in seconds"""
        return time.time() - self.connected_at


@dataclass
class ServerMetrics:
    """
    Global server metrics (Python 3.13 style)
    Thread-safe metrics collection
    """

    started_at: float = field(default_factory=time.time)

    # Connection tracking
    total_connections: int = 0
    active_connections: int = 0
    failed_auth_attempts: int = 0

    # Per-connection metrics
    connections: dict[str, ConnectionMetrics] = field(default_factory=dict)

    # Lock for thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Class variable for singleton pattern
    _instance: ClassVar['ServerMetrics | None'] = None

    @classmethod
    def get_instance(cls) -> 'ServerMetrics':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_connection(self, client_id: str) -> ConnectionMetrics:
        """Register new connection"""
        with self._lock:
            self.total_connections += 1
            self.active_connections += 1

            metrics = ConnectionMetrics(client_id=client_id)
            self.connections[client_id] = metrics
            return metrics

    def unregister_connection(self, client_id: str):
        """Unregister connection"""
        with self._lock:
            if client_id in self.connections:
                self.active_connections -= 1
                # Keep metrics for reporting, just mark as inactive

    def record_failed_auth(self):
        """Record failed authentication attempt"""
        with self._lock:
            self.failed_auth_attempts += 1

    def get_connection_metrics(self, client_id: str) -> ConnectionMetrics | None:
        """Get metrics for specific connection"""
        with self._lock:
            return self.connections.get(client_id)

    @property
    def uptime_seconds(self) -> float:
        """Server uptime in seconds"""
        return time.time() - self.started_at

    def get_summary(self) -> dict[str, any]:
        """Get metrics summary"""
        with self._lock:
            # Aggregate statistics across all active connections
            total_frames = sum(
                m.frames_sent for m in self.connections.values()
                if time.time() - m.last_activity < 300  # Active in last 5 min
            )

            total_bytes_sent = sum(
                m.bytes_sent for m in self.connections.values()
            )

            avg_fps = 0.0
            active_connections = [
                m for m in self.connections.values()
                if time.time() - m.last_activity < 60  # Active in last minute
            ]

            if active_connections:
                avg_fps = sum(m.fps for m in active_connections) / len(active_connections)

            return {
                'uptime_seconds': self.uptime_seconds,
                'total_connections': self.total_connections,
                'active_connections': self.active_connections,
                'failed_auth_attempts': self.failed_auth_attempts,
                'total_frames_sent': total_frames,
                'total_bytes_sent': total_bytes_sent,
                'avg_fps': avg_fps,
            }

    def format_summary(self) -> str:
        """Format metrics as human-readable string"""
        summary = self.get_summary()

        uptime_hours = summary['uptime_seconds'] / 3600
        mb_sent = summary['total_bytes_sent'] / (1024 * 1024)

        return f"""
Server Metrics:
  Uptime: {uptime_hours:.2f} hours
  Connections: {summary['active_connections']} active, {summary['total_connections']} total
  Failed auth: {summary['failed_auth_attempts']}
  Data sent: {mb_sent:.2f} MB
  Frames sent: {summary['total_frames_sent']}
  Avg FPS: {summary['avg_fps']:.1f}
        """.strip()


class PerformanceMonitor:
    """
    Context manager for performance monitoring
    Python 3.13 compatible
    """

    def __init__(self, operation_name: str, logger: logging.Logger | None = None):
        """
        Initialize performance monitor

        Args:
            operation_name: Name of operation being monitored
            logger: Logger instance
        """
        self.operation_name = operation_name
        self.logger = logger or logging.getLogger(__name__)
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def __enter__(self) -> 'PerformanceMonitor':
        """Start monitoring"""
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop monitoring and log results"""
        self.end_time = time.perf_counter()
        duration = self.end_time - self.start_time

        if exc_type is None:
            # Success
            self.logger.debug(
                f"{self.operation_name} completed in {duration*1000:.2f}ms"
            )
        else:
            # Error occurred
            self.logger.warning(
                f"{self.operation_name} failed after {duration*1000:.2f}ms: {exc_val}"
            )

        return False  # Don't suppress exceptions

    @property
    def duration(self) -> float:
        """Get operation duration in seconds"""
        if self.end_time > 0:
            return self.end_time - self.start_time
        return time.perf_counter() - self.start_time


def format_bytes(bytes_count: int) -> str:
    """Format byte count as human-readable string"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.2f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.2f} TB"


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string"""
    if seconds < 1:
        return f"{seconds*1000:.2f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"
