# PyVNCServer v3.1 - New Features Guide

This guide covers all the new features introduced in PyVNCServer v3.1, which builds on the Python 3.13 enhancements from v3.0.

## Table of Contents

1. [Session Recording and Playback](#session-recording-and-playback)
2. [Clipboard Synchronization](#clipboard-synchronization)
3. [Prometheus Metrics Export](#prometheus-metrics-export)
4. [Structured Logging](#structured-logging)
5. [Advanced Connection Pooling](#advanced-connection-pooling)
6. [Performance Monitoring](#performance-monitoring)

---

## Session Recording and Playback

Record VNC sessions for audit trails, debugging, and playback.

### Features

- **Compressed storage**: Uses gzip compression to save disk space
- **Multiple event types**: Captures all VNC protocol messages
- **Metadata support**: Add custom metadata to events
- **Playback control**: Seek, filter, and replay at different speeds
- **Statistics**: Detailed session analytics

### Basic Usage

```python
from vnc_lib import SessionRecorder, SessionPlayer, EventType
from pathlib import Path

# Record a session
session_file = Path('session.vnc.gz')

with SessionRecorder(session_file, compress=True) as recorder:
    recorder.record_handshake(b'RFB 003.008\n')
    recorder.record_auth(auth_type=1, success=True)
    recorder.record_init(width=1920, height=1080, name='Desktop')

    # Record user interactions
    recorder.record_key_event(key=65, down=True)  # 'A' key
    recorder.record_pointer_event(x=100, y=200, button_mask=1)

    # Record errors
    recorder.record_error('Connection timeout')

    print(f"Recorded {recorder.event_count} events")
```

### Playback

```python
# Load and play back
with SessionPlayer(session_file) as player:
    # Get statistics
    stats = player.get_statistics()
    print(f"Total events: {stats['total_events']}")
    print(f"Duration: {stats['duration_seconds']}s")
    print(f"Event breakdown: {stats['event_counts']}")

    # Get specific event types
    key_events = player.get_events({EventType.KEY_EVENT})

    # Play back in real-time
    for event in player.play(speed=1.0):
        print(f"{event.timestamp}: {event.event_type.name}")

    # Or at 2x speed
    for event in player.play(speed=2.0):
        process_event(event)
```

### Advanced Features

```python
# Seek to specific timestamp
player.seek(10.5)  # Seek to 10.5 seconds

# Filter by event type
input_events = player.get_events({
    EventType.KEY_EVENT,
    EventType.POINTER_EVENT
})

# Get detailed statistics
stats = player.get_statistics()
# Returns: {
#     'total_events': 150,
#     'duration_seconds': 45.3,
#     'events_per_second': 3.31,
#     'event_counts': {'KEY_EVENT': 45, 'POINTER_EVENT': 105},
#     'session_id': '20250110_143022',
#     'start_time': '2025-01-10T14:30:22.123456Z'
# }
```

---

## Clipboard Synchronization

Full clipboard synchronization between VNC client and server.

### Features

- **Bidirectional sync**: Client ↔ Server
- **Size limits**: Configurable maximum clipboard size
- **Format support**: Text (with encoding detection)
- **History tracking**: Maintain clipboard history
- **Callbacks**: React to clipboard changes
- **Security**: Sanitization and validation

### Basic Usage

```python
from vnc_lib import ClipboardManager

# Create manager
manager = ClipboardManager(
    max_size=1024 * 1024,  # 1MB limit
    encoding='utf-8'
)

# Set server clipboard (sends to client)
message = manager.set_server_clipboard('Server text')
if message:
    send_to_client(message)  # VNC ServerCutText message

# Handle client clipboard
client_message = receive_from_client()
manager.handle_client_cut_text(client_message)

# Get clipboard content
server_text = manager.get_server_clipboard_text()
client_text = manager.get_client_clipboard_text()
```

### Callbacks

```python
# Register callbacks for clipboard changes
def on_client_clipboard(data):
    print(f"Client clipboard: {data.text}")
    # Update system clipboard
    pyperclip.copy(data.text)

def on_server_clipboard(data):
    print(f"Server clipboard: {data.text}")

manager.on_client_update(on_client_clipboard)
manager.on_server_update(on_server_clipboard)
```

### Clipboard History

```python
from vnc_lib import ClipboardHistory

history = ClipboardHistory(max_entries=100)

# Add to history
history.add(clipboard_data)

# Get recent entries
recent = history.get_recent(count=10)

# Get statistics
stats = history.get_stats()
# Returns: {
#     'entry_count': 45,
#     'max_entries': 100,
#     'total_size_bytes': 12345,
#     'average_size_bytes': 274
# }
```

### Security Features

```python
from vnc_lib.clipboard import sanitize_clipboard_text

# Sanitize clipboard text
safe_text = sanitize_clipboard_text(
    user_input,
    max_length=1_000_000
)
# Removes: null bytes, control characters (except newlines/tabs)
# Normalizes: line endings to \n
```

---

## Prometheus Metrics Export

Export VNC server metrics in Prometheus format via HTTP endpoint.

### Features

- **HTTP endpoint**: Standard `/metrics` endpoint
- **Standard metrics**: Connections, bandwidth, framebuffer updates, etc.
- **Custom metrics**: Add your own metrics
- **Thread-safe**: Safe for concurrent access
- **VNC-specific collector**: Pre-configured VNC metrics

### Basic Usage

```python
from vnc_lib import PrometheusExporter

# Start metrics exporter
with PrometheusExporter(host='0.0.0.0', port=9100) as exporter:
    print(f"Metrics at: {exporter.url}")

    # Get the collector
    collector = exporter.collector

    # Record VNC activity
    collector.record_connection(success=True)
    collector.set_active_connections(5)
    collector.record_bytes_sent(1024, encoding='zrle')
    collector.record_framebuffer_update(
        rect_count=10,
        duration=0.025,
        encoding='hextile'
    )
    collector.record_key_event()
    collector.record_pointer_event()
    collector.record_error('timeout')

    # Metrics automatically available at http://0.0.0.0:9100/metrics
```

### Standard VNC Metrics

The following metrics are automatically collected:

- `vnc_connections_total` - Total connections (counter)
- `vnc_connections_active` - Active connections (gauge)
- `vnc_connections_failed_total` - Failed connections (counter)
- `vnc_bytes_sent_total` - Bytes sent to clients (counter)
- `vnc_bytes_received_total` - Bytes received from clients (counter)
- `vnc_framebuffer_updates_total` - Framebuffer updates sent (counter)
- `vnc_framebuffer_rectangles_total` - Rectangles sent (counter)
- `vnc_framebuffer_update_duration_seconds` - Update duration (gauge)
- `vnc_key_events_total` - Keyboard events (counter)
- `vnc_pointer_events_total` - Pointer events (counter)
- `vnc_encoding_bytes_total` - Bytes by encoding type (counter)
- `vnc_errors_total` - Errors by type (counter)
- `vnc_server_uptime_seconds` - Server uptime (gauge)

### Custom Metrics

```python
from vnc_lib import MetricsRegistry, MetricType

registry = MetricsRegistry()

# Register custom metrics
registry.register(
    'custom_metric',
    MetricType.GAUGE,
    'My custom metric'
)

# Set values
registry.set_gauge('cpu_usage', 45.5, labels={'host': 'server1'})
registry.increment_counter('requests_total', labels={'method': 'GET'})

# Export
metrics_text = registry.to_prometheus_format()
```

---

## Structured Logging

Enhanced logging with context, correlation IDs, and JSON output.

### Features

- **Structured output**: JSON or human-readable
- **Context management**: Thread-local context
- **Correlation IDs**: Track request flows
- **Performance logging**: Automatic timing
- **Audit logging**: Compliance-ready audit trails
- **Python 3.13 pattern matching**: For log level handling

### Basic Usage

```python
from vnc_lib import get_logger, configure_logging

# Configure global logging
configure_logging(
    level='INFO',
    json_format=False,  # or True for JSON
    log_file='vnc_server.log'
)

# Create logger
logger = get_logger('vnc_server')

# Basic logging
logger.info("Server starting", port=5900, host='0.0.0.0')
logger.warning("High connection count", connections=50)
logger.error("Connection failed", exc_info=True, client='192.168.1.100')
```

### Context Management

```python
from vnc_lib import LogContext

# Add context to all logs in a scope
with LogContext(user='alice', session_id='abc123'):
    logger.info("User connected")
    logger.info("Processing request")
    # All logs include user and session_id
```

### Correlation IDs

```python
from vnc_lib import CorrelationContext

# Track related operations
with CorrelationContext('request-456'):
    logger.info("Handling request")
    process_request()
    logger.info("Request complete")
    # All logs include correlation_id
```

### Performance Logging

```python
from vnc_lib import PerformanceLogger

# Automatically log operation duration
with PerformanceLogger(logger, 'encode_frame', threshold_seconds=0.01):
    encode_framebuffer()
    # Logs duration if > 10ms
```

### Audit Logging

```python
from vnc_lib.structured_logging import AuditLogger

audit_log = AuditLogger('audit.log')

# Log security events
audit_log.log_connection(
    client_ip='192.168.1.100',
    success=True,
    user='alice',
    auth_type='password'
)

audit_log.log_authentication(
    user='alice',
    auth_type='password',
    success=True
)

audit_log.log_access(
    user='alice',
    resource='framebuffer',
    action='read'
)
```

---

## Advanced Connection Pooling

Sophisticated connection pooling with health checks and resource management.

### Features

- **Size limits**: Min/max pool size
- **Health checks**: Automatic connection validation
- **Age limits**: Recycle old connections
- **Idle timeout**: Close idle connections
- **Metrics**: Detailed pool statistics
- **Thread-safe**: Concurrent access support
- **Auto-cleanup**: Background cleanup thread

### Basic Usage

```python
from vnc_lib import AdvancedConnectionPool

pool = AdvancedConnectionPool(
    max_size=100,
    min_size=10,
    max_idle_time=300.0,  # 5 minutes
    max_connection_age=3600.0  # 1 hour
)

# Add connections
socket_conn = create_connection()
pooled_conn = pool.add_connection(socket_conn)

# Acquire connection
conn = pool.acquire(timeout=5.0)
if conn:
    try:
        # Use connection
        conn.connection.send(data)
        conn.metrics.add_bytes_sent(len(data))
    finally:
        # Release back to pool
        pool.release(conn, reuse=True)

# Get statistics
stats = pool.get_stats()
print(f"Active: {stats['active_connections']}")
print(f"Idle: {stats['idle_connections']}")
print(f"Total requests: {stats['total_requests']}")
```

### Pool Manager

```python
from vnc_lib import ConnectionPoolManager

# Manage multiple pools
with ConnectionPoolManager(cleanup_interval=60.0) as manager:
    # Create pools
    pool1 = manager.create_pool('main', max_size=100)
    pool2 = manager.create_pool('backup', max_size=50)

    # Get pool by name
    pool = manager.get_pool('main')

    # Get all stats
    stats = manager.get_stats()
```

### Health Checks

```python
def check_connection_health(socket_conn):
    """Custom health check function."""
    try:
        # Try a simple operation
        socket_conn.getpeername()
        return True
    except:
        return False

pool = AdvancedConnectionPool(
    max_size=100,
    health_check=check_connection_health
)
```

---

## Performance Monitoring

Comprehensive performance monitoring and profiling tools.

### Features

- **High-precision timing**: Uses `perf_counter`
- **Statistical analysis**: Mean, median, percentiles
- **Resource tracking**: CPU, memory, I/O
- **Memory profiling**: GC statistics
- **Decorators**: Easy function timing
- **Minimal overhead**: Negligible performance impact

### Basic Usage

```python
from vnc_lib import get_global_monitor, time_function

monitor = get_global_monitor()

# Time an operation
with monitor.time_operation('encode_frame'):
    encode_framebuffer()

# Get statistics
stats = monitor.get_stats('encode_frame')
print(f"Mean: {stats.mean * 1000:.3f}ms")
print(f"P95: {stats.p95 * 1000:.3f}ms")
print(f"P99: {stats.p99 * 1000:.3f}ms")
```

### Function Decorator

```python
@time_function('process_request')
def process_request(data):
    # Function is automatically timed
    return process(data)
```

### Performance Timer

```python
from vnc_lib import PerformanceTimer

timer = PerformanceTimer('my_operation')

timer.start()
do_work()
duration = timer.stop()

print(f"Duration: {timer.duration_ms:.3f}ms")

# Or with context manager
with PerformanceTimer('operation') as timer:
    do_work()
    timer.add_metadata(items=100)
```

### Resource Monitoring

```python
from vnc_lib.performance_monitor import ResourceMonitor

monitor = ResourceMonitor()

# Get current usage
usage = monitor.get_current_usage()
print(f"User time: {usage['user_time']}s")
print(f"System time: {usage['system_time']}s")
print(f"Max RSS: {usage['max_rss_kb']} KB")

# Get delta since start
delta = monitor.get_delta_usage()
print(f"CPU time used: {delta['user_time']}s")

# Sample periodically
monitor.sample()
# ... later ...
samples = monitor.get_samples()
```

### Memory Profiling

```python
from vnc_lib.performance_monitor import MemoryProfiler

profiler = MemoryProfiler()

# Get GC statistics
gc_stats = profiler.get_gc_stats()
print(f"Total objects: {gc_stats['total_objects']}")
print(f"Collections: {gc_stats['total_collections']}")

# Force collection
collected = profiler.force_collection()
print(f"Collected {collected} objects")

# Track over time
profiler.sample_gc()
# ... later ...
samples = profiler.get_gc_samples()
```

### Analysis Features

```python
# Get slowest operations
slowest = monitor.get_slowest_operations(limit=10)
for operation, mean_duration in slowest:
    print(f"{operation}: {mean_duration * 1000:.3f}ms")

# Get summary
summary = monitor.get_summary()
# Returns complete performance overview

# Clear specific operation
monitor.clear('encode_frame')

# Clear all
monitor.clear()
```

---

## Integration Example

Here's a complete example integrating all v3.1 features:

```python
from vnc_lib import (
    SessionRecorder, ClipboardManager, PrometheusExporter,
    get_logger, LogContext, get_global_monitor
)

# Setup
logger = get_logger('vnc_server')
session_recorder = SessionRecorder('session.vnc.gz')
clipboard = ClipboardManager()
monitor = get_global_monitor()

# Start Prometheus exporter
with PrometheusExporter(port=9100) as exporter:
    collector = exporter.collector

    # Handle client connection
    with LogContext(client_ip='192.168.1.100'):
        with monitor.time_operation('handle_client'):
            logger.info("Client connected")
            collector.record_connection(success=True)

            with session_recorder:
                # Record session
                session_recorder.record_handshake(b'RFB 003.008\n')

                # Handle clipboard
                clipboard.set_server_clipboard('Welcome!')

                # Process events...
                collector.record_bytes_sent(1024, 'zrle')
                collector.record_key_event()

            logger.info("Session complete",
                       events=session_recorder.event_count)
```

---

## Python 3.13 Features Used

All modules utilize Python 3.13 features:

- **Type parameter syntax** (PEP 695): Better type safety
- **Pattern matching**: Clean message handling
- **Exception groups** (PEP 654): Multi-error handling
- **Context variables**: Thread-local context
- **Improved typing**: Generic type parameters
- **Performance**: Faster execution

---

## Best Practices

1. **Session Recording**: Use compression for production, uncompressed for debugging
2. **Clipboard**: Set appropriate size limits for security
3. **Metrics**: Export to Prometheus for monitoring
4. **Logging**: Use JSON format for production, human-readable for development
5. **Connection Pooling**: Enable health checks and auto-cleanup
6. **Performance**: Monitor only critical operations to minimize overhead

---

## See Also

- [README.md](README.md) - Main documentation
- [PYTHON313_FEATURES.md](PYTHON313_FEATURES.md) - Python 3.13 features
- [examples/advanced_features_demo.py](examples/advanced_features_demo.py) - Complete examples
- [RFC 6143](https://tools.ietf.org/html/rfc6143) - VNC Protocol Specification
