"""Tests for Prometheus metrics exporter functionality."""

import pytest
import time
import requests
from urllib.error import URLError

from vnc_lib.prometheus_exporter import (
    MetricsRegistry, VNCMetricsCollector, PrometheusExporter,
    MetricType, MetricValue, Metric
)


class TestMetricValue:
    """Test MetricValue functionality."""

    def test_metric_value_creation(self):
        """Test creating a metric value."""
        value = MetricValue(
            name='test_metric',
            value=42.0,
            labels={'host': 'localhost', 'port': '5900'}
        )

        assert value.name == 'test_metric'
        assert value.value == 42.0
        assert value.labels['host'] == 'localhost'

    def test_metric_value_to_prometheus_line(self):
        """Test converting to Prometheus format."""
        # Without labels
        value = MetricValue(name='simple_metric', value=100.0)
        line = value.to_prometheus_line()
        assert line == 'simple_metric 100.0'

        # With labels
        value = MetricValue(
            name='labeled_metric',
            value=200.0,
            labels={'method': 'GET', 'status': '200'}
        )
        line = value.to_prometheus_line()
        assert 'labeled_metric{' in line
        assert 'method="GET"' in line
        assert 'status="200"' in line
        assert '} 200.0' in line


class TestMetric:
    """Test Metric functionality."""

    def test_metric_creation(self):
        """Test creating a metric."""
        metric = Metric(
            name='test_counter',
            metric_type=MetricType.COUNTER,
            help_text='A test counter'
        )

        assert metric.name == 'test_counter'
        assert metric.metric_type == MetricType.COUNTER
        assert len(metric.values) == 0

    def test_add_value(self):
        """Test adding values to metric."""
        metric = Metric('test_gauge', MetricType.GAUGE, 'Test gauge')

        metric.add_value(10.0)
        metric.add_value(20.0, {'label': 'value'})

        assert len(metric.values) == 2

    def test_set_value(self):
        """Test setting metric value (replaces existing)."""
        metric = Metric('test_gauge', MetricType.GAUGE, 'Test gauge')

        # Set value with labels
        metric.set_value(10.0, {'host': 'server1'})
        assert len(metric.values) == 1
        assert metric.values[0].value == 10.0

        # Set same labels again (should replace)
        metric.set_value(20.0, {'host': 'server1'})
        assert len(metric.values) == 1
        assert metric.values[0].value == 20.0

        # Set different labels (should add)
        metric.set_value(30.0, {'host': 'server2'})
        assert len(metric.values) == 2

    def test_to_prometheus_format(self):
        """Test converting to Prometheus text format."""
        metric = Metric('vnc_connections', MetricType.GAUGE, 'Active connections')
        metric.add_value(5.0)

        output = metric.to_prometheus_format()

        assert '# HELP vnc_connections Active connections' in output
        assert '# TYPE vnc_connections gauge' in output
        assert 'vnc_connections 5.0' in output

    def test_clear(self):
        """Test clearing metric values."""
        metric = Metric('test_counter', MetricType.COUNTER, 'Test')
        metric.add_value(10.0)
        metric.add_value(20.0)

        assert len(metric.values) == 2

        metric.clear()
        assert len(metric.values) == 0


class TestMetricsRegistry:
    """Test MetricsRegistry functionality."""

    def test_registry_creation(self):
        """Test creating metrics registry."""
        registry = MetricsRegistry()
        assert registry.metric_count == 0

    def test_register_metric(self):
        """Test registering a metric."""
        registry = MetricsRegistry()

        metric = registry.register(
            'test_metric',
            MetricType.COUNTER,
            'A test metric'
        )

        assert metric.name == 'test_metric'
        assert registry.metric_count == 1

    def test_register_duplicate(self):
        """Test registering same metric twice returns existing."""
        registry = MetricsRegistry()

        metric1 = registry.register('test', MetricType.COUNTER, 'Test')
        metric2 = registry.register('test', MetricType.COUNTER, 'Test')

        assert metric1 is metric2
        assert registry.metric_count == 1

    def test_get_metric(self):
        """Test getting a metric by name."""
        registry = MetricsRegistry()

        registry.register('test', MetricType.GAUGE, 'Test')
        metric = registry.get_metric('test')

        assert metric is not None
        assert metric.name == 'test'

    def test_get_nonexistent_metric(self):
        """Test getting a metric that doesn't exist."""
        registry = MetricsRegistry()
        metric = registry.get_metric('nonexistent')
        assert metric is None

    def test_set_gauge(self):
        """Test setting a gauge value."""
        registry = MetricsRegistry()

        registry.set_gauge('cpu_usage', 45.5, help_text='CPU usage')

        metric = registry.get_metric('cpu_usage')
        assert metric is not None
        assert len(metric.values) == 1
        assert metric.values[0].value == 45.5

    def test_increment_counter(self):
        """Test incrementing a counter."""
        registry = MetricsRegistry()

        registry.increment_counter('requests_total', help_text='Total requests')
        registry.increment_counter('requests_total')
        registry.increment_counter('requests_total', value=3.0)

        metric = registry.get_metric('requests_total')
        assert metric is not None
        assert metric.values[0].value == 5.0

    def test_to_prometheus_format(self):
        """Test exporting all metrics in Prometheus format."""
        registry = MetricsRegistry()

        registry.set_gauge('temperature', 72.5)
        registry.increment_counter('events_total', value=10)

        output = registry.to_prometheus_format()

        assert 'temperature' in output
        assert 'events_total' in output
        assert '72.5' in output
        assert '10' in output

    def test_clear(self):
        """Test clearing all metrics."""
        registry = MetricsRegistry()

        registry.set_gauge('test1', 10.0)
        registry.set_gauge('test2', 20.0)

        registry.clear()

        # Metrics still registered but values cleared
        assert registry.metric_count == 2
        metric1 = registry.get_metric('test1')
        assert len(metric1.values) == 0

    def test_clear_specific_metric(self):
        """Test clearing a specific metric."""
        registry = MetricsRegistry()

        registry.set_gauge('test1', 10.0)
        registry.set_gauge('test2', 20.0)

        registry.clear_metric('test1')

        metric1 = registry.get_metric('test1')
        metric2 = registry.get_metric('test2')

        assert len(metric1.values) == 0
        assert len(metric2.values) == 1

    def test_thread_safety(self):
        """Test that registry is thread-safe."""
        import threading

        registry = MetricsRegistry()

        def increment_counter():
            for _ in range(100):
                registry.increment_counter('test_counter')

        threads = [threading.Thread(target=increment_counter) for _ in range(10)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        metric = registry.get_metric('test_counter')
        # Should be 1000 (10 threads * 100 increments)
        assert metric.values[0].value == 1000.0


class TestVNCMetricsCollector:
    """Test VNCMetricsCollector functionality."""

    def test_collector_creation(self):
        """Test creating VNC metrics collector."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        # Check that standard metrics are registered
        assert registry.get_metric('vnc_connections_total') is not None
        assert registry.get_metric('vnc_bytes_sent_total') is not None

    def test_record_connection(self):
        """Test recording connections."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        collector.record_connection(success=True)
        collector.record_connection(success=True)
        collector.record_connection(success=False)

        total = registry.get_metric('vnc_connections_total')
        failed = registry.get_metric('vnc_connections_failed_total')

        assert total.values[0].value == 2.0
        assert failed.values[0].value == 1.0

    def test_set_active_connections(self):
        """Test setting active connection count."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        collector.set_active_connections(5)

        metric = registry.get_metric('vnc_connections_active')
        assert metric.values[0].value == 5.0

    def test_record_bytes(self):
        """Test recording bytes sent/received."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        collector.record_bytes_sent(1024, encoding='raw')
        collector.record_bytes_sent(2048, encoding='zrle')
        collector.record_bytes_received(512)

        sent = registry.get_metric('vnc_bytes_sent_total')
        received = registry.get_metric('vnc_bytes_received_total')

        assert sent.values[0].value == 3072.0
        assert received.values[0].value == 512.0

    def test_record_framebuffer_update(self):
        """Test recording framebuffer updates."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        collector.record_framebuffer_update(
            rect_count=5,
            duration=0.05,
            encoding='hextile'
        )

        updates = registry.get_metric('vnc_framebuffer_updates_total')
        rects = registry.get_metric('vnc_framebuffer_rectangles_total')
        duration = registry.get_metric('vnc_framebuffer_update_duration_seconds')

        assert updates.values[0].value >= 1.0
        assert rects.values[0].value == 5.0
        assert duration.values[0].value == 0.05

    def test_record_input_events(self):
        """Test recording input events."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        collector.record_key_event()
        collector.record_key_event()
        collector.record_pointer_event()

        keys = registry.get_metric('vnc_key_events_total')
        pointer = registry.get_metric('vnc_pointer_events_total')

        assert keys.values[0].value == 2.0
        assert pointer.values[0].value == 1.0

    def test_record_error(self):
        """Test recording errors."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        collector.record_error('protocol_error')
        collector.record_error('protocol_error')
        collector.record_error('encoding_error')

        errors = registry.get_metric('vnc_errors_total')

        # Find errors by label
        protocol_errors = [v for v in errors.values if v.labels.get('type') == 'protocol_error']
        encoding_errors = [v for v in errors.values if v.labels.get('type') == 'encoding_error']

        assert protocol_errors[0].value == 2.0
        assert encoding_errors[0].value == 1.0

    def test_update_uptime(self):
        """Test updating server uptime."""
        registry = MetricsRegistry()
        collector = VNCMetricsCollector(registry)

        time.sleep(0.01)  # Small delay
        collector.update_uptime()

        uptime = registry.get_metric('vnc_server_uptime_seconds')
        assert uptime.values[0].value > 0


class TestPrometheusExporter:
    """Test PrometheusExporter functionality."""

    def test_exporter_creation(self):
        """Test creating Prometheus exporter."""
        exporter = PrometheusExporter(host='127.0.0.1', port=0)  # port 0 = random

        assert exporter.collector is not None
        assert exporter.registry is not None
        assert not exporter.is_running

    def test_exporter_start_stop(self):
        """Test starting and stopping exporter."""
        exporter = PrometheusExporter(host='127.0.0.1', port=0)

        exporter.start()
        time.sleep(0.1)  # Give server time to start
        assert exporter.is_running

        exporter.stop()
        assert not exporter.is_running

    def test_exporter_context_manager(self):
        """Test exporter context manager."""
        with PrometheusExporter(host='127.0.0.1', port=0) as exporter:
            time.sleep(0.1)
            assert exporter.is_running

        # Should be stopped after exiting context
        assert not exporter.is_running

    def test_url_property(self):
        """Test URL property."""
        exporter = PrometheusExporter(host='127.0.0.1', port=9100)
        assert exporter.url == 'http://127.0.0.1:9100/metrics'

    # Note: We skip actual HTTP tests as they require network access
    # and a running server, which can be flaky in CI environments
