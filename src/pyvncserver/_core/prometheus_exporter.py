"""
Prometheus Metrics Exporter

Provides an HTTP endpoint for exporting VNC server metrics in Prometheus format.
Uses only Python standard library (http.server, threading).

Uses Python 3.13 features:
- Type parameter syntax
- Pattern matching
- Better threading utilities
"""

import time
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Protocol
import sys
if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self
from dataclasses import dataclass, field
from collections.abc import Callable
import enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, enum.Enum):
        """StrEnum polyfill for Python < 3.11."""
        def __new__(cls, value):
            return str.__new__(cls, value)


class MetricType(StrEnum):
    """Prometheus metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass(slots=True)
class MetricValue:
    """Represents a single metric value with labels."""

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_prometheus_line(self) -> str:
        """Convert to Prometheus text format line."""
        if self.labels:
            labels_str = ','.join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
            return f'{self.name}{{{labels_str}}} {self.value}'
        return f'{self.name} {self.value}'


@dataclass(slots=True)
class Metric:
    """Represents a Prometheus metric with metadata."""

    name: str
    metric_type: MetricType
    help_text: str
    values: list[MetricValue] = field(default_factory=list)

    def add_value(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Add a value to this metric."""
        metric_value = MetricValue(
            name=self.name,
            value=value,
            labels=labels or {}
        )
        self.values.append(metric_value)

    def set_value(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Set the value for this metric (replaces existing with same labels)."""
        labels = labels or {}

        # Find existing value with same labels
        for i, mv in enumerate(self.values):
            if mv.labels == labels:
                self.values[i] = MetricValue(
                    name=self.name,
                    value=value,
                    labels=labels
                )
                return

        # No existing value found, add new one
        self.add_value(value, labels)

    def to_prometheus_format(self) -> str:
        """Convert to Prometheus text format."""
        lines = [
            f'# HELP {self.name} {self.help_text}',
            f'# TYPE {self.name} {self.metric_type}'
        ]

        for value in self.values:
            lines.append(value.to_prometheus_line())

        return '\n'.join(lines)

    def clear(self) -> None:
        """Clear all values."""
        self.values.clear()


class MetricsRegistry:
    """
    Registry for all Prometheus metrics.

    Thread-safe collection of metrics with automatic registration.
    """

    __slots__ = ('_metrics', '_lock')

    def __init__(self):
        self._metrics: dict[str, Metric] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        metric_type: MetricType,
        help_text: str
    ) -> Metric:
        """Register a new metric."""
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]

            metric = Metric(name, metric_type, help_text)
            self._metrics[name] = metric
            return metric

    def get_metric(self, name: str) -> Metric | None:
        """Get a metric by name."""
        with self._lock:
            return self._metrics.get(name)

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        help_text: str = ""
    ) -> None:
        """Set a gauge metric value."""
        with self._lock:
            metric = self._metrics.get(name)
            if not metric:
                metric = self.register(name, MetricType.GAUGE, help_text)
            metric.set_value(value, labels)

    def increment_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
        help_text: str = ""
    ) -> None:
        """Increment a counter metric."""
        with self._lock:
            metric = self._metrics.get(name)
            if not metric:
                metric = self.register(name, MetricType.COUNTER, help_text)

            labels = labels or {}

            # Find existing counter with same labels
            for mv in metric.values:
                if mv.labels == labels:
                    mv.value += value
                    mv.timestamp = time.time()
                    return

            # No existing counter, create new
            metric.add_value(value, labels)

    def to_prometheus_format(self) -> str:
        """Export all metrics in Prometheus text format."""
        with self._lock:
            if not self._metrics:
                return "# No metrics registered\n"

            return '\n\n'.join(
                metric.to_prometheus_format()
                for metric in self._metrics.values()
            ) + '\n'

    def clear(self) -> None:
        """Clear all metrics."""
        with self._lock:
            for metric in self._metrics.values():
                metric.clear()

    def clear_metric(self, name: str) -> None:
        """Clear a specific metric."""
        with self._lock:
            metric = self._metrics.get(name)
            if metric:
                metric.clear()

    @property
    def metric_count(self) -> int:
        """Get number of registered metrics."""
        with self._lock:
            return len(self._metrics)


class VNCMetricsCollector:
    """
    Collects VNC server metrics for Prometheus export.

    Tracks common VNC server statistics like connections, bandwidth, etc.
    """

    __slots__ = ('_registry', '_start_time')

    def __init__(self, registry: MetricsRegistry):
        self._registry = registry
        self._start_time = time.time()

        # Register standard VNC metrics
        self._register_standard_metrics()

    def _register_standard_metrics(self) -> None:
        """Register all standard VNC server metrics."""
        # Connection metrics
        self._registry.register(
            'vnc_connections_total',
            MetricType.COUNTER,
            'Total number of VNC connections'
        )
        self._registry.register(
            'vnc_connections_active',
            MetricType.GAUGE,
            'Number of currently active VNC connections'
        )
        self._registry.register(
            'vnc_connections_failed_total',
            MetricType.COUNTER,
            'Total number of failed VNC connections'
        )
        self._registry.register(
            'vnc_failed_auth_attempts_total',
            MetricType.COUNTER,
            'Total failed VNC authentication attempts'
        )

        # Bandwidth metrics
        self._registry.register(
            'vnc_bytes_sent_total',
            MetricType.COUNTER,
            'Total bytes sent to clients'
        )
        self._registry.register(
            'vnc_bytes_received_total',
            MetricType.COUNTER,
            'Total bytes received from clients'
        )

        # Framebuffer metrics
        self._registry.register(
            'vnc_framebuffer_updates_total',
            MetricType.COUNTER,
            'Total number of framebuffer updates sent'
        )
        self._registry.register(
            'vnc_framebuffer_rectangles_total',
            MetricType.COUNTER,
            'Total number of rectangles sent'
        )
        self._registry.register(
            'vnc_framebuffer_update_duration_seconds',
            MetricType.GAUGE,
            'Duration of last framebuffer update'
        )

        # Input metrics
        self._registry.register(
            'vnc_key_events_total',
            MetricType.COUNTER,
            'Total number of keyboard events'
        )
        self._registry.register(
            'vnc_pointer_events_total',
            MetricType.COUNTER,
            'Total number of pointer events'
        )

        # Encoding metrics
        self._registry.register(
            'vnc_encoding_bytes_total',
            MetricType.COUNTER,
            'Total bytes by encoding type'
        )

        # Error metrics
        self._registry.register(
            'vnc_errors_total',
            MetricType.COUNTER,
            'Total number of errors by type'
        )

        # Server metrics
        self._registry.register(
            'vnc_server_uptime_seconds',
            MetricType.GAUGE,
            'VNC server uptime in seconds'
        )

    def record_connection(self, success: bool = True) -> None:
        """Record a connection attempt."""
        if success:
            self._registry.increment_counter('vnc_connections_total')
        else:
            self._registry.increment_counter('vnc_connections_failed_total')

    def set_active_connections(self, count: int) -> None:
        """Set the number of active connections."""
        self._registry.set_gauge('vnc_connections_active', float(count))

    def record_bytes_sent(self, bytes_count: int, encoding: str = "") -> None:
        """Record bytes sent to client."""
        self._registry.increment_counter('vnc_bytes_sent_total', float(bytes_count))
        if encoding:
            self._registry.increment_counter(
                'vnc_encoding_bytes_total',
                float(bytes_count),
                {'encoding': encoding}
            )

    def record_bytes_received(self, bytes_count: int) -> None:
        """Record bytes received from client."""
        self._registry.increment_counter('vnc_bytes_received_total', float(bytes_count))

    def record_framebuffer_update(
        self,
        rect_count: int,
        duration: float,
        encoding: str = ""
    ) -> None:
        """Record a framebuffer update."""
        self._registry.increment_counter('vnc_framebuffer_updates_total')
        self._registry.increment_counter('vnc_framebuffer_rectangles_total', float(rect_count))
        self._registry.set_gauge('vnc_framebuffer_update_duration_seconds', duration)

        if encoding:
            self._registry.increment_counter(
                'vnc_framebuffer_updates_total',
                1.0,
                {'encoding': encoding}
            )

    def record_key_event(self) -> None:
        """Record a keyboard event."""
        self._registry.increment_counter('vnc_key_events_total')

    def record_pointer_event(self) -> None:
        """Record a pointer event."""
        self._registry.increment_counter('vnc_pointer_events_total')

    def record_error(self, error_type: str) -> None:
        """Record an error."""
        self._registry.increment_counter('vnc_errors_total', 1.0, {'type': error_type})

    def update_uptime(self) -> None:
        """Update server uptime metric."""
        uptime = time.time() - self._start_time
        self._registry.set_gauge('vnc_server_uptime_seconds', uptime)


class PrometheusHandler(BaseHTTPRequestHandler):
    """HTTP request handler for metrics, health, readiness and status."""

    registry: MetricsRegistry | None = None
    status_provider: Callable[[], dict] | None = None

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == '/metrics':
            self.send_metrics()
        elif self.path in {'/health', '/healthz', '/'}:
            self.send_health()
        elif self.path == '/readyz':
            self.send_ready()
        elif self.path == '/status':
            self.send_status()
        else:
            self.send_error(404, "Not Found")

    def _sync_status_metrics(self) -> None:
        if not self.registry:
            return
        status = self._status()
        mappings = {
            'vnc_server_uptime_seconds': status.get('uptime_seconds', 0.0),
            'vnc_connections_active': status.get('active_connections', 0),
            'vnc_connections_total': status.get('total_connections', 0),
            'vnc_failed_auth_attempts_total': status.get('failed_auth_attempts', 0),
            'vnc_adaptive_target_fps': status.get('avg_adaptive_target_fps', 0.0),
            'vnc_adaptive_pressure': status.get('avg_adaptive_pressure', 0.0),
            'vnc_adaptive_overloaded_connections': status.get('overloaded_connections', 0),
            'vnc_server_ready': 1.0 if status.get('ready', False) else 0.0,
            'vnc_server_healthy': 1.0 if status.get('healthy', False) else 0.0,
        }
        for name, value in mappings.items():
            self.registry.set_gauge(name, float(value), help_text=f'PyVNCServer runtime metric: {name}')
        cache = status.get('encoded_region_cache') or {}
        if isinstance(cache, dict):
            for key in ('entries', 'bytes', 'hits', 'misses', 'evictions'):
                if key in cache:
                    self.registry.set_gauge(
                        f'vnc_encoded_region_cache_{key}', float(cache[key]),
                        help_text=f'Encoded-region cache {key}',
                    )

    def send_metrics(self) -> None:
        """Send live metrics in Prometheus format."""
        if not self.registry:
            self.send_error(500, "Metrics registry not initialized")
            return
        self._sync_status_metrics()
        metrics_text = self.registry.to_prometheus_format()

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(metrics_text)))
        self.end_headers()
        self.wfile.write(metrics_text.encode('utf-8'))

    def _status(self) -> dict:
        provider = type(self).status_provider
        if provider is None:
            return {'healthy': True, 'ready': True}
        try:
            return dict(provider())
        except Exception as exc:
            return {'healthy': False, 'ready': False, 'status_error': str(exc)}

    def send_health(self) -> None:
        """Return liveness as plain text for probes."""
        status = self._status()
        healthy = bool(status.get('healthy', False))
        response = ('OK' if healthy else 'UNHEALTHY') + '\n'
        self.send_response(200 if healthy else 503)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def send_ready(self) -> None:
        """Return readiness/capacity separately from liveness."""
        status = self._status()
        ready = bool(status.get('ready', False))
        response = ('READY' if ready else 'NOT READY') + '\n'
        self.send_response(200 if ready else 503)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def send_status(self) -> None:
        payload = json.dumps(self._status(), sort_keys=True).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        """Override to reduce logging noise."""
        # Only log errors
        if args[1] != '200':
            super().log_message(format, *args)


class PrometheusExporter:
    """
    HTTP server for exporting Prometheus metrics.

    Runs in a background thread and exposes metrics on /metrics endpoint.
    """

    __slots__ = ('_registry', '_collector', '_server', '_thread',
                 '_host', '_port', '_running', '_status_provider')

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 9100,
        registry: MetricsRegistry | None = None,
        status_provider: Callable[[], dict] | None = None,
    ):
        self._host = host
        self._port = port
        self._registry = registry or MetricsRegistry()
        self._collector = VNCMetricsCollector(self._registry)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._status_provider = status_provider


    def start(self) -> None:
        """Start the Prometheus metrics HTTP server."""
        if self._running:
            return

        handler_type = type('BoundPrometheusHandler', (PrometheusHandler,), {})
        handler_type.registry = self._registry
        handler_type.status_provider = self._status_provider
        self._server = HTTPServer((self._host, self._port), handler_type)
        # Set socket timeout so handle_request doesn't block forever
        self._server.socket.settimeout(1.0)
        self._running = True

        # Start server in background thread
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def _run_server(self) -> None:
        """Run the HTTP server (called in background thread)."""
        if not self._server:
            return

        while self._running:
            try:
                self._server.handle_request()
            except Exception:
                # Timeout or other errors - continue if still running
                pass

    def stop(self) -> None:
        """Stop the Prometheus metrics HTTP server."""
        self._running = False

        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    @property
    def collector(self) -> VNCMetricsCollector:
        """Get the metrics collector."""
        return self._collector

    @property
    def registry(self) -> MetricsRegistry:
        """Get the metrics registry."""
        return self._registry

    @property
    def is_running(self) -> bool:
        """Check if the exporter is running."""
        return self._running

    @property
    def bound_port(self) -> int:
        return int(self._server.server_port) if self._server is not None else int(self._port)

    @property
    def url(self) -> str:
        """Get the metrics endpoint URL."""
        return f"http://{self._host}:{self.bound_port}/metrics"

    @property
    def health_url(self) -> str:
        return f"http://{self._host}:{self.bound_port}/healthz"

    @property
    def readiness_url(self) -> str:
        return f"http://{self._host}:{self.bound_port}/readyz"

    @property
    def status_url(self) -> str:
        return f"http://{self._host}:{self.bound_port}/status"

    def __enter__(self) -> Self:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        self.stop()
        return False
