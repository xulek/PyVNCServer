#!/usr/bin/env python3
"""
Advanced Features Demo

Demonstrates the new features in PyVNCServer v3.1:
- Session recording and playback
- Clipboard synchronization
- Prometheus metrics export
- Structured logging
- Performance monitoring
"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vnc_lib import (
    # Session recording
    SessionRecorder, SessionPlayer,

    # Clipboard
    ClipboardManager,

    # Prometheus metrics
    PrometheusExporter,

    # Structured logging
    StructuredLogger, LogContext, configure_logging,

    # Performance monitoring
    get_global_monitor, time_function,
)


def demo_session_recording():
    """Demonstrate session recording and playback."""
    print("\n=== Session Recording Demo ===")

    session_file = Path('demo_session.vnc.gz')

    # Record a session
    print("Recording session...")
    with SessionRecorder(session_file) as recorder:
        recorder.record_handshake(b'RFB 003.008\n')
        recorder.record_auth(1, True)
        recorder.record_init(1920, 1080, 'Demo Desktop')

        # Simulate some interactions
        for i in range(5):
            recorder.record_key_event(65 + i, True)  # Keys A-E
            time.sleep(0.01)
            recorder.record_pointer_event(100 * i, 200, 1)

        print(f"Recorded {recorder.event_count} events in {recorder.duration:.3f}s")

    # Play back the session
    print("\nPlaying back session...")
    with SessionPlayer(session_file) as player:
        stats = player.get_statistics()
        print(f"Total events: {stats['total_events']}")
        print(f"Duration: {stats['duration_seconds']}s")
        print(f"Events per second: {stats['events_per_second']}")
        print(f"Event breakdown: {stats['event_counts']}")

        # Get specific event types
        key_events = player.get_events({player._events[0].event_type.__class__.KEY_EVENT})
        print(f"Key events: {len(key_events)}")

    # Cleanup
    session_file.unlink()
    print("Session recording demo complete!")


def demo_clipboard():
    """Demonstrate clipboard synchronization."""
    print("\n=== Clipboard Synchronization Demo ===")

    manager = ClipboardManager(max_size=1024 * 10)  # 10KB limit

    # Register callbacks
    def on_client_update(data):
        print(f"Client clipboard updated: {data.text[:50]}...")

    def on_server_update(data):
        print(f"Server clipboard updated: {data.text[:50]}...")

    manager.on_client_update(on_client_update)
    manager.on_server_update(on_server_update)

    # Set server clipboard
    print("\nSetting server clipboard...")
    message = manager.set_server_clipboard("Hello from VNC server!")
    if message:
        print(f"Sent ServerCutText message ({len(message)} bytes)")

    # Simulate client clipboard update
    import struct
    client_text = b'Client clipboard content'
    client_msg = bytearray()
    client_msg.append(6)  # ClientCutText
    client_msg.extend(b'\x00\x00\x00')
    client_msg.extend(struct.pack('!I', len(client_text)))
    client_msg.extend(client_text)

    print("\nHandling client clipboard...")
    manager.handle_client_cut_text(bytes(client_msg))

    # Get statistics
    stats = manager.get_stats()
    print(f"\nClipboard stats:")
    print(f"  Enabled: {stats['enabled']}")
    print(f"  Max size: {stats['max_size']} bytes")
    print(f"  Server content size: {stats['server_content_size']} bytes")
    print(f"  Client content size: {stats['client_content_size']} bytes")

    print("Clipboard demo complete!")


def demo_prometheus_metrics():
    """Demonstrate Prometheus metrics export."""
    print("\n=== Prometheus Metrics Demo ===")

    # Start metrics exporter on port 9100
    with PrometheusExporter(host='127.0.0.1', port=9100) as exporter:
        print(f"Metrics available at: {exporter.url}")

        # Get the collector
        collector = exporter.collector

        # Simulate some VNC activity
        print("\nSimulating VNC activity...")

        # Record connections
        collector.record_connection(success=True)
        collector.record_connection(success=True)
        collector.set_active_connections(2)

        # Record bandwidth
        collector.record_bytes_sent(1024 * 100, encoding='raw')
        collector.record_bytes_sent(1024 * 50, encoding='zrle')
        collector.record_bytes_received(1024 * 10)

        # Record framebuffer updates
        collector.record_framebuffer_update(
            rect_count=5,
            duration=0.025,
            encoding='hextile'
        )

        # Record input events
        for _ in range(10):
            collector.record_key_event()

        for _ in range(20):
            collector.record_pointer_event()

        # Update uptime
        collector.update_uptime()

        # Get metrics in Prometheus format
        metrics_text = exporter.registry.to_prometheus_format()

        print("\nSample metrics:")
        for line in metrics_text.split('\n')[:15]:
            if line and not line.startswith('#'):
                print(f"  {line}")

        print(f"\nTotal metrics: {exporter.registry.metric_count}")
        print(f"Server running: {exporter.is_running}")

        print("\nMetrics exporter will stop automatically...")
        time.sleep(1)

    print("Prometheus metrics demo complete!")


def demo_structured_logging():
    """Demonstrate structured logging."""
    print("\n=== Structured Logging Demo ===")

    # Configure global logging
    configure_logging(json_format=False)

    # Create a logger
    logger = StructuredLogger('vnc_demo', json_format=False)

    # Basic logging
    print("\nBasic logging:")
    logger.info("VNC server starting", port=5900, host='0.0.0.0')
    logger.warning("High connection count", connections=50)

    # Logging with context
    print("\nLogging with context:")
    with LogContext(user='alice', session_id='abc123'):
        logger.info("User connected")
        logger.info("Processing request", request_type='framebuffer_update')

    # Logging with correlation ID
    print("\nLogging with correlation ID:")
    logger.set_correlation_id('req-456')
    logger.info("Handling client request")
    logger.clear_correlation_id()

    # Performance logging
    print("\nPerformance logging:")
    from vnc_lib.structured_logging import PerformanceLogger

    with PerformanceLogger(logger, 'encode_frame', threshold_seconds=0.0):
        # Simulate work
        time.sleep(0.01)

    print("Structured logging demo complete!")


@time_function('demo_performance_monitoring')
def demo_performance_monitoring():
    """Demonstrate performance monitoring."""
    print("\n=== Performance Monitoring Demo ===")

    monitor = get_global_monitor()
    monitor.enable()

    # Time some operations
    print("\nTiming operations...")

    with monitor.time_operation('operation_1'):
        time.sleep(0.01)

    with monitor.time_operation('operation_2') as op:
        time.sleep(0.02)
        op.add_metadata(items_processed=100)

    # Record multiple samples
    for i in range(10):
        with monitor.time_operation('fast_operation'):
            time.sleep(0.001)

    # Get statistics
    print("\nPerformance statistics:")

    stats = monitor.get_stats('fast_operation')
    if stats:
        print(f"  Operation: fast_operation")
        print(f"    Count: {stats.count}")
        print(f"    Mean: {stats.mean * 1000:.3f}ms")
        print(f"    Min: {stats.min * 1000:.3f}ms")
        print(f"    Max: {stats.max * 1000:.3f}ms")
        print(f"    P95: {stats.p95 * 1000:.3f}ms")
        print(f"    P99: {stats.p99 * 1000:.3f}ms")

    # Get slowest operations
    print("\nSlowest operations:")
    slowest = monitor.get_slowest_operations(limit=3)
    for op, mean_duration in slowest:
        print(f"  {op}: {mean_duration * 1000:.3f}ms")

    # Resource monitoring
    print("\nResource monitoring:")
    from vnc_lib.performance_monitor import ResourceMonitor

    resource_monitor = ResourceMonitor()
    usage = resource_monitor.get_current_usage()
    print(f"  User time: {usage['user_time']:.3f}s")
    print(f"  System time: {usage['system_time']:.3f}s")
    print(f"  Max RSS: {usage['max_rss_kb']} KB")

    # Memory profiling
    print("\nMemory profiling:")
    from vnc_lib.performance_monitor import MemoryProfiler

    mem_profiler = MemoryProfiler()
    gc_stats = mem_profiler.get_gc_stats()
    print(f"  Total objects: {gc_stats['total_objects']}")
    print(f"  Gen 0 collections: {gc_stats['generation_0']}")

    print("Performance monitoring demo complete!")


def main():
    """Run all demos."""
    print("=" * 60)
    print("PyVNCServer v3.1 - Advanced Features Demo")
    print("=" * 60)

    try:
        demo_session_recording()
        demo_clipboard()
        demo_prometheus_metrics()
        demo_structured_logging()
        demo_performance_monitoring()

        print("\n" + "=" * 60)
        print("All demos completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError running demos: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
