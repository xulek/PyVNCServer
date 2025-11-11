"""
Performance Monitoring and Profiling Module

Advanced performance monitoring, profiling, and benchmarking utilities.
Tracks CPU, memory, I/O, and custom metrics with minimal overhead.

Uses Python 3.13 features:
- Type parameter syntax
- Pattern matching
- Better timing utilities
"""

import time
import threading
import sys
import gc
from dataclasses import dataclass, field
from typing import Self, Any
from collections.abc import Callable
from collections import deque
from statistics import mean, median, stdev
from contextvars import ContextVar

# Conditional import for resource module (Unix/Linux only)
if sys.platform != 'win32':
    import resource
else:
    resource = None


# Context variable for performance tracking
_perf_context: ContextVar[dict[str, Any]] = ContextVar('perf_context', default={})


@dataclass(slots=True)
class TimingStats:
    """Statistical summary of timing measurements."""

    count: int
    total: float
    min: float
    max: float
    mean: float
    median: float
    stdev: float
    p95: float
    p99: float

    def to_dict(self) -> dict[str, float | int]:
        """Convert to dictionary."""
        return {
            'count': self.count,
            'total': self.total,
            'min': self.min,
            'max': self.max,
            'mean': self.mean,
            'median': self.median,
            'stdev': self.stdev,
            'p95': self.p95,
            'p99': self.p99
        }


@dataclass(slots=True)
class PerformanceSample:
    """Single performance measurement sample."""

    timestamp: float
    duration: float
    operation: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        return self.duration * 1000.0


class PerformanceTimer:
    """
    High-precision timer for measuring operation performance.

    Uses perf_counter for best accuracy.
    """

    __slots__ = ('_operation', '_start_time', '_end_time', '_metadata')

    def __init__(self, operation: str):
        self._operation = operation
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._metadata: dict[str, Any] = {}

    def start(self) -> Self:
        """Start the timer."""
        self._start_time = time.perf_counter()
        return self

    def stop(self) -> float:
        """Stop the timer and return duration."""
        self._end_time = time.perf_counter()
        return self.duration

    def add_metadata(self, **metadata: Any) -> None:
        """Add metadata to this timing."""
        self._metadata.update(metadata)

    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        if self._end_time == 0:
            return time.perf_counter() - self._start_time
        return self._end_time - self._start_time

    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        return self.duration * 1000.0

    def to_sample(self) -> PerformanceSample:
        """Convert to performance sample."""
        return PerformanceSample(
            timestamp=self._start_time,
            duration=self.duration,
            operation=self._operation,
            metadata=self._metadata.copy()
        )

    def __enter__(self) -> Self:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        self.stop()
        return False


class PerformanceCollector:
    """
    Collects and analyzes performance measurements.

    Maintains a sliding window of recent measurements with statistical analysis.
    """

    __slots__ = ('_operation', '_samples', '_max_samples', '_lock')

    def __init__(self, operation: str, max_samples: int = 1000):
        self._operation = operation
        self._samples: deque[PerformanceSample] = deque(maxlen=max_samples)
        self._max_samples = max_samples
        self._lock = threading.Lock()

    def record(self, duration: float, **metadata: Any) -> None:
        """Record a performance measurement."""
        sample = PerformanceSample(
            timestamp=time.time(),
            duration=duration,
            operation=self._operation,
            metadata=metadata
        )

        with self._lock:
            self._samples.append(sample)

    def get_stats(self) -> TimingStats | None:
        """Calculate statistics from collected samples."""
        with self._lock:
            if not self._samples:
                return None

            durations = [s.duration for s in self._samples]
            sorted_durations = sorted(durations)

            count = len(durations)
            total = sum(durations)

            # Calculate percentiles
            p95_idx = int(count * 0.95)
            p99_idx = int(count * 0.99)

            return TimingStats(
                count=count,
                total=total,
                min=sorted_durations[0],
                max=sorted_durations[-1],
                mean=mean(durations),
                median=median(durations),
                stdev=stdev(durations) if count > 1 else 0.0,
                p95=sorted_durations[p95_idx] if p95_idx < count else sorted_durations[-1],
                p99=sorted_durations[p99_idx] if p99_idx < count else sorted_durations[-1]
            )

    def get_recent_samples(self, count: int = 10) -> list[PerformanceSample]:
        """Get the most recent samples."""
        with self._lock:
            samples = list(self._samples)
            return samples[-count:] if count < len(samples) else samples

    def clear(self) -> None:
        """Clear all samples."""
        with self._lock:
            self._samples.clear()

    @property
    def sample_count(self) -> int:
        """Get number of collected samples."""
        with self._lock:
            return len(self._samples)


class PerformanceMonitor:
    """
    Central performance monitoring system.

    Tracks multiple operations and provides aggregate statistics.
    """

    __slots__ = ('_collectors', '_lock', '_enabled')

    def __init__(self):
        self._collectors: dict[str, PerformanceCollector] = {}
        self._lock = threading.RLock()
        self._enabled = True

    def enable(self) -> None:
        """Enable performance monitoring."""
        self._enabled = True

    def disable(self) -> None:
        """Disable performance monitoring."""
        self._enabled = False

    def get_timer(self, operation: str) -> PerformanceTimer:
        """Get a timer for an operation."""
        return PerformanceTimer(operation)

    def record(self, operation: str, duration: float, **metadata: Any) -> None:
        """Record a performance measurement."""
        if not self._enabled:
            return

        with self._lock:
            if operation not in self._collectors:
                self._collectors[operation] = PerformanceCollector(operation)

            self._collectors[operation].record(duration, **metadata)

    def time_operation(self, operation: str) -> 'TimedOperation':
        """Create a context manager for timing an operation."""
        return TimedOperation(self, operation)

    def get_stats(self, operation: str) -> TimingStats | None:
        """Get statistics for a specific operation."""
        with self._lock:
            collector = self._collectors.get(operation)
            if collector:
                return collector.get_stats()
            return None

    def get_all_stats(self) -> dict[str, TimingStats]:
        """Get statistics for all operations."""
        with self._lock:
            stats = {}
            for operation, collector in self._collectors.items():
                collector_stats = collector.get_stats()
                if collector_stats:
                    stats[operation] = collector_stats
            return stats

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all performance metrics."""
        all_stats = self.get_all_stats()

        summary = {
            'operation_count': len(all_stats),
            'enabled': self._enabled,
            'operations': {}
        }

        for operation, stats in all_stats.items():
            summary['operations'][operation] = stats.to_dict()

        return summary

    def clear(self, operation: str | None = None) -> None:
        """Clear statistics for an operation or all operations."""
        with self._lock:
            if operation:
                collector = self._collectors.get(operation)
                if collector:
                    collector.clear()
            else:
                for collector in self._collectors.values():
                    collector.clear()

    def get_slowest_operations(self, limit: int = 10) -> list[tuple[str, float]]:
        """Get the slowest operations by average duration."""
        all_stats = self.get_all_stats()

        operations_with_mean = [
            (op, stats.mean)
            for op, stats in all_stats.items()
        ]

        # Sort by mean duration descending
        operations_with_mean.sort(key=lambda x: x[1], reverse=True)

        return operations_with_mean[:limit]

    @property
    def is_enabled(self) -> bool:
        """Check if monitoring is enabled."""
        return self._enabled


class TimedOperation:
    """
    Context manager for timing operations with automatic recording.

    Usage:
        with monitor.time_operation('my_operation'):
            # Do work
            pass
    """

    __slots__ = ('_monitor', '_operation', '_timer', '_metadata')

    def __init__(self, monitor: PerformanceMonitor, operation: str):
        self._monitor = monitor
        self._operation = operation
        self._timer = PerformanceTimer(operation)
        self._metadata: dict[str, Any] = {}

    def add_metadata(self, **metadata: Any) -> None:
        """Add metadata to this operation."""
        self._metadata.update(metadata)

    def __enter__(self) -> Self:
        """Start timing."""
        self._timer.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Stop timing and record."""
        duration = self._timer.stop()

        # Add exception info if present
        if exc_type:
            self._metadata['error'] = exc_type.__name__

        self._monitor.record(self._operation, duration, **self._metadata)
        return False


class ResourceMonitor:
    """
    Monitors system resource usage (CPU time, memory, etc.).

    Uses the resource module for accurate resource tracking on Unix/Linux.
    On Windows, provides basic fallback metrics using psutil or system time.
    """

    __slots__ = ('_initial_usage', '_samples', '_lock', '_is_unix')

    def __init__(self):
        self._is_unix = resource is not None
        if self._is_unix:
            self._initial_usage = resource.getrusage(resource.RUSAGE_SELF)
        else:
            self._initial_usage = None
        self._samples: list[tuple[float, Any]] = []
        self._lock = threading.Lock()

    def get_current_usage(self) -> dict[str, float]:
        """Get current resource usage."""
        if self._is_unix and resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return {
                'user_time': usage.ru_utime,
                'system_time': usage.ru_stime,
                'max_rss_kb': usage.ru_maxrss,
                'page_faults': usage.ru_majflt,
                'block_input': usage.ru_inblock,
                'block_output': usage.ru_oublock,
                'voluntary_context_switches': usage.ru_nvcsw,
                'involuntary_context_switches': usage.ru_nivcsw
            }
        else:
            # Windows fallback: return zeros or basic metrics
            return {
                'user_time': 0.0,
                'system_time': 0.0,
                'max_rss_kb': 0.0,
                'page_faults': 0.0,
                'block_input': 0.0,
                'block_output': 0.0,
                'voluntary_context_switches': 0.0,
                'involuntary_context_switches': 0.0
            }

    def get_delta_usage(self) -> dict[str, float]:
        """Get resource usage delta since initialization."""
        if self._is_unix and resource is not None and self._initial_usage is not None:
            current = resource.getrusage(resource.RUSAGE_SELF)
            return {
                'user_time': current.ru_utime - self._initial_usage.ru_utime,
                'system_time': current.ru_stime - self._initial_usage.ru_stime,
                'max_rss_kb': current.ru_maxrss - self._initial_usage.ru_maxrss,
                'page_faults': current.ru_majflt - self._initial_usage.ru_majflt,
                'block_input': current.ru_inblock - self._initial_usage.ru_inblock,
                'block_output': current.ru_oublock - self._initial_usage.ru_oublock
            }
        else:
            # Windows fallback: return zeros
            return {
                'user_time': 0.0,
                'system_time': 0.0,
                'max_rss_kb': 0.0,
                'page_faults': 0.0,
                'block_input': 0.0,
                'block_output': 0.0
            }

    def sample(self) -> None:
        """Take a snapshot of current resource usage."""
        with self._lock:
            self._samples.append((time.time(), self.get_current_usage()))

    def get_samples(self) -> list[tuple[float, Any]]:
        """Get all resource usage samples."""
        with self._lock:
            return self._samples.copy()

    def clear_samples(self) -> None:
        """Clear all samples."""
        with self._lock:
            self._samples.clear()


class MemoryProfiler:
    """
    Tracks memory allocations and garbage collection statistics.

    Useful for detecting memory leaks and optimization opportunities.
    """

    __slots__ = ('_initial_objects', '_gc_stats', '_lock')

    def __init__(self):
        self._initial_objects = len(gc.get_objects())
        self._gc_stats: list[dict[str, int]] = []
        self._lock = threading.Lock()

    def get_gc_stats(self) -> dict[str, Any]:
        """Get garbage collection statistics."""
        gc_counts = gc.get_count()

        return {
            'generation_0': gc_counts[0],
            'generation_1': gc_counts[1],
            'generation_2': gc_counts[2],
            'total_collections': sum(gc.get_stats()[g]['collections']
                                    for g in range(3)),
            'total_objects': len(gc.get_objects()),
            'delta_objects': len(gc.get_objects()) - self._initial_objects
        }

    def sample_gc(self) -> None:
        """Take a snapshot of GC statistics."""
        with self._lock:
            self._gc_stats.append(self.get_gc_stats())

    def force_collection(self) -> int:
        """Force a garbage collection and return number of objects collected."""
        return gc.collect()

    def get_gc_samples(self) -> list[dict[str, int]]:
        """Get all GC samples."""
        with self._lock:
            return self._gc_stats.copy()

    def clear_samples(self) -> None:
        """Clear all GC samples."""
        with self._lock:
            self._gc_stats.clear()


# Global performance monitor instance
_global_monitor = PerformanceMonitor()


def get_global_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance."""
    return _global_monitor


def time_function(operation: str | None = None) -> Callable:
    """
    Decorator for timing function execution.

    Usage:
        @time_function('my_function')
        def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        op_name = operation or func.__name__

        def wrapper(*args, **kwargs):
            with _global_monitor.time_operation(op_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
