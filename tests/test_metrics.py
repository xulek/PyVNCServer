"""
Unit tests for metrics and monitoring
Python 3.13 compatible
"""

import unittest
import time
from vnc_lib.metrics import (
    ConnectionMetrics, ServerMetrics, PerformanceMonitor, format_bytes, format_duration
)


class TestConnectionMetrics(unittest.TestCase):
    """Test ConnectionMetrics class"""

    def test_metrics_creation(self):
        """Test metrics initialization"""
        metrics = ConnectionMetrics(client_id="test-client")
        self.assertEqual(metrics.client_id, "test-client")
        self.assertEqual(metrics.frames_sent, 0)
        self.assertEqual(metrics.bytes_sent, 0)

    def test_record_frame(self):
        """Test frame recording"""
        metrics = ConnectionMetrics(client_id="test")

        metrics.record_frame(bytes_sent=1024, encoding_time=0.01, original_size=4096)

        self.assertEqual(metrics.frames_sent, 1)
        self.assertEqual(metrics.bytes_sent, 1024)
        self.assertGreater(len(metrics.encoding_times), 0)
        self.assertGreater(len(metrics.compression_ratios), 0)

    def test_avg_encoding_time(self):
        """Test average encoding time calculation"""
        metrics = ConnectionMetrics(client_id="test")

        metrics.record_frame(1024, 0.01, 4096)
        metrics.record_frame(1024, 0.02, 4096)
        metrics.record_frame(1024, 0.03, 4096)

        avg_time = metrics.avg_encoding_time
        self.assertAlmostEqual(avg_time, 0.02, places=2)

    def test_avg_compression_ratio(self):
        """Test average compression ratio"""
        metrics = ConnectionMetrics(client_id="test")

        metrics.record_frame(1024, 0.01, 4096)  # 25% compression
        metrics.record_frame(2048, 0.01, 4096)  # 50% compression

        avg_ratio = metrics.avg_compression_ratio
        self.assertAlmostEqual(avg_ratio, 0.375, places=2)

    def test_record_input(self):
        """Test input event recording"""
        metrics = ConnectionMetrics(client_id="test")

        metrics.record_input('key')
        metrics.record_input('key')
        metrics.record_input('pointer')

        self.assertEqual(metrics.key_events, 2)
        self.assertEqual(metrics.pointer_events, 1)

    def test_uptime(self):
        """Test uptime calculation"""
        metrics = ConnectionMetrics(client_id="test")
        time.sleep(0.1)

        uptime = metrics.uptime_seconds
        self.assertGreaterEqual(uptime, 0.1)


class TestServerMetrics(unittest.TestCase):
    """Test ServerMetrics class"""

    def setUp(self):
        """Setup fresh metrics instance"""
        # Reset singleton
        ServerMetrics._instance = None

    def test_singleton(self):
        """Test singleton pattern"""
        metrics1 = ServerMetrics.get_instance()
        metrics2 = ServerMetrics.get_instance()

        self.assertIs(metrics1, metrics2)

    def test_register_connection(self):
        """Test connection registration"""
        metrics = ServerMetrics.get_instance()

        conn_metrics = metrics.register_connection("client-1")

        self.assertEqual(metrics.total_connections, 1)
        self.assertEqual(metrics.active_connections, 1)
        self.assertIsNotNone(conn_metrics)

    def test_unregister_connection(self):
        """Test connection unregistration"""
        metrics = ServerMetrics.get_instance()

        metrics.register_connection("client-1")
        metrics.unregister_connection("client-1")

        self.assertEqual(metrics.active_connections, 0)

    def test_failed_auth(self):
        """Test failed authentication recording"""
        metrics = ServerMetrics.get_instance()

        metrics.record_failed_auth()
        metrics.record_failed_auth()

        self.assertEqual(metrics.failed_auth_attempts, 2)

    def test_get_summary(self):
        """Test metrics summary"""
        metrics = ServerMetrics.get_instance()

        metrics.register_connection("client-1")
        summary = metrics.get_summary()

        self.assertIn('uptime_seconds', summary)
        self.assertIn('total_connections', summary)
        self.assertIn('active_connections', summary)
        self.assertEqual(summary['total_connections'], 1)
        self.assertEqual(summary['active_connections'], 1)


class TestPerformanceMonitor(unittest.TestCase):
    """Test PerformanceMonitor context manager"""

    def test_monitor_success(self):
        """Test successful operation monitoring"""
        import logging
        logger = logging.getLogger('test')

        with PerformanceMonitor("test operation", logger) as monitor:
            time.sleep(0.01)

        duration = monitor.duration
        self.assertGreaterEqual(duration, 0.01)

    def test_monitor_error(self):
        """Test error handling in monitor"""
        import logging
        logger = logging.getLogger('test')

        try:
            with PerformanceMonitor("test operation", logger):
                raise ValueError("Test error")
        except ValueError:
            pass  # Expected


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions"""

    def test_format_bytes(self):
        """Test byte formatting"""
        self.assertEqual(format_bytes(100), "100.00 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.00 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024), "1.00 GB")

    def test_format_duration(self):
        """Test duration formatting"""
        self.assertIn("ms", format_duration(0.001))
        self.assertIn("s", format_duration(1.5))
        self.assertIn("m", format_duration(65))
        self.assertIn("h", format_duration(3661))


if __name__ == '__main__':
    unittest.main()
