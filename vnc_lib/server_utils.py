"""
Server utilities for graceful shutdown, health checks, and lifecycle management
Python 3.13 compatible
"""

import signal
import threading
import logging
import time
import ipaddress
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class NetworkProfile(Enum):
    """Network profile for connection optimization"""
    LOCALHOST = "localhost"
    LAN = "lan"
    WAN = "wan"


def detect_network_profile(client_ip: str) -> NetworkProfile:
    """
    Detect network profile based on client IP address.

    Args:
        client_ip: Client IP address string

    Returns:
        NetworkProfile enum value
    """
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        # If we can't parse it, treat as WAN (safest default)
        return NetworkProfile.WAN

    # Loopback -> LOCALHOST
    if addr.is_loopback:
        return NetworkProfile.LOCALHOST

    # Private networks (10.x, 172.16-31.x, 192.168.x) and link-local -> LAN
    if addr.is_private or addr.is_link_local:
        return NetworkProfile.LAN

    return NetworkProfile.WAN


@dataclass
class HealthStatus:
    """Server health status (Python 3.13 style)"""
    is_healthy: bool
    uptime_seconds: float
    active_connections: int
    total_connections: int
    last_error: str | None = None
    error_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'healthy': self.is_healthy,
            'uptime': self.uptime_seconds,
            'active_connections': self.active_connections,
            'total_connections': self.total_connections,
            'last_error': self.last_error,
            'error_count': self.error_count,
        }


class GracefulShutdown:
    """
    Handles graceful server shutdown with cleanup
    Python 3.13 compatible with modern features
    """

    def __init__(self):
        """Initialize graceful shutdown handler"""
        self.logger = logging.getLogger(__name__)
        self.shutdown_event = threading.Event()
        self.cleanup_callbacks: list[Callable[[], None]] = []
        self._signal_received = False

        # Register signal handlers
        self._register_signals()

    def _register_signals(self):
        """Register signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            """Handle shutdown signals"""
            sig_name = signal.Signals(signum).name
            self.logger.info(f"Received signal {sig_name}, initiating graceful shutdown...")
            self._signal_received = True
            self.shutdown_event.set()

        # Register handlers for common shutdown signals
        try:
            signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
            signal.signal(signal.SIGTERM, signal_handler)  # Kill command

            # SIGHUP on Unix systems
            if hasattr(signal, 'SIGHUP'):
                signal.signal(signal.SIGHUP, signal_handler)

        except Exception as e:
            self.logger.warning(f"Failed to register signal handlers: {e}")

    def register_cleanup(self, callback: Callable[[], None]):
        """
        Register cleanup callback

        Args:
            callback: Function to call during shutdown
        """
        self.cleanup_callbacks.append(callback)
        self.logger.debug(f"Registered cleanup callback: {callback.__name__}")

    def is_shutting_down(self) -> bool:
        """Check if shutdown has been initiated"""
        return self.shutdown_event.is_set()

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """
        Wait for shutdown signal

        Args:
            timeout: Maximum time to wait (None = indefinite)

        Returns:
            True if shutdown was signaled, False if timeout
        """
        return self.shutdown_event.wait(timeout=timeout)

    def shutdown(self):
        """Initiate graceful shutdown"""
        if self.shutdown_event.is_set():
            self.logger.warning("Shutdown already in progress")
            return

        self.logger.info("Initiating graceful shutdown...")
        self.shutdown_event.set()

        # Run cleanup callbacks
        for callback in self.cleanup_callbacks:
            try:
                self.logger.debug(f"Running cleanup: {callback.__name__}")
                callback()
            except Exception as e:
                self.logger.error(f"Cleanup callback failed: {e}", exc_info=True)

        self.logger.info("Graceful shutdown complete")


class HealthChecker:
    """
    Periodic health check system
    Python 3.13 compatible
    """

    def __init__(self, check_interval: float = 30.0):
        """
        Initialize health checker

        Args:
            check_interval: Interval between health checks in seconds
        """
        self.check_interval = check_interval
        self.logger = logging.getLogger(__name__)

        self.health_checks: dict[str, Callable[[], bool]] = {}
        self.last_check_time: float = 0.0
        self.last_status: HealthStatus | None = None

        self._running = False
        self._thread: threading.Thread | None = None

    def register_check(self, name: str, check_func: Callable[[], bool]):
        """
        Register health check function

        Args:
            name: Name of the health check
            check_func: Function that returns True if healthy
        """
        self.health_checks[name] = check_func
        self.logger.debug(f"Registered health check: {name}")

    def start(self):
        """Start periodic health checking"""
        if self._running:
            self.logger.warning("Health checker already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop,
            name="HealthChecker",
            daemon=True
        )
        self._thread.start()
        self.logger.info("Health checker started")

    def stop(self):
        """Stop health checking"""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self.logger.info("Health checker stopped")

    def _check_loop(self):
        """Main health check loop"""
        while self._running:
            try:
                self._perform_checks()
            except Exception as e:
                self.logger.error(f"Health check error: {e}", exc_info=True)

            # Sleep with interrupt check
            for _ in range(int(self.check_interval * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def _perform_checks(self):
        """Perform all registered health checks"""
        all_healthy = True
        failed_checks: list[str] = []

        for name, check_func in self.health_checks.items():
            try:
                is_healthy = check_func()
                if not is_healthy:
                    all_healthy = False
                    failed_checks.append(name)
            except Exception as e:
                self.logger.error(f"Health check '{name}' failed: {e}")
                all_healthy = False
                failed_checks.append(name)

        if not all_healthy:
            self.logger.warning(f"Health check failed: {', '.join(failed_checks)}")

        self.last_check_time = time.time()

    def get_status(self, uptime: float, active_conns: int,
                  total_conns: int) -> HealthStatus:
        """
        Get current health status

        Args:
            uptime: Server uptime in seconds
            active_conns: Number of active connections
            total_conns: Total connection count

        Returns:
            HealthStatus object
        """
        # Run all checks
        all_healthy = True
        for name, check_func in self.health_checks.items():
            try:
                if not check_func():
                    all_healthy = False
                    break
            except:
                all_healthy = False
                break

        status = HealthStatus(
            is_healthy=all_healthy,
            uptime_seconds=uptime,
            active_connections=active_conns,
            total_connections=total_conns,
        )

        self.last_status = status
        return status


class ConnectionPool:
    """
    Thread-safe connection pool
    Python 3.13 compatible
    """

    def __init__(self, max_connections: int = 10):
        """
        Initialize connection pool

        Args:
            max_connections: Maximum number of concurrent connections
        """
        self.max_connections = max_connections
        self.logger = logging.getLogger(__name__)

        self.active_connections: set[str] = set()
        self.connection_semaphore = threading.Semaphore(max_connections)
        self._lock = threading.Lock()

    def acquire(self, client_id: str, timeout: float = 30.0) -> bool:
        """
        Acquire connection slot

        Args:
            client_id: Unique client identifier
            timeout: Maximum time to wait for slot

        Returns:
            True if slot acquired, False if timeout
        """
        acquired = self.connection_semaphore.acquire(timeout=timeout)

        if acquired:
            with self._lock:
                self.active_connections.add(client_id)
            self.logger.debug(
                f"Connection acquired: {client_id} "
                f"({len(self.active_connections)}/{self.max_connections})"
            )
            return True
        else:
            self.logger.warning(f"Connection pool full, rejected: {client_id}")
            return False

    def release(self, client_id: str):
        """
        Release connection slot

        Args:
            client_id: Client identifier to release
        """
        was_active = False
        with self._lock:
            if client_id in self.active_connections:
                self.active_connections.remove(client_id)
                was_active = True

        if was_active:
            self.connection_semaphore.release()
            self.logger.debug(
                f"Connection released: {client_id} "
                f"({len(self.active_connections)}/{self.max_connections})"
            )
        else:
            self.logger.warning(f"Connection release called for unknown client: {client_id}")

    def get_active_count(self) -> int:
        """Get number of active connections"""
        with self._lock:
            return len(self.active_connections)

    def is_full(self) -> bool:
        """Check if connection pool is full"""
        return self.get_active_count() >= self.max_connections


class PerformanceThrottler:
    """
    Rate limiter for performance control
    Python 3.13 compatible
    """

    def __init__(self, max_rate: float):
        """
        Initialize throttler

        Args:
            max_rate: Maximum operations per second
        """
        self.max_rate = max_rate
        self.min_interval = 1.0 / max_rate if max_rate > 0 else 0.0
        self.last_operation_time: float = 0.0
        self._lock = threading.Lock()

    def throttle(self):
        """
        Throttle operation to maintain max rate
        Sleeps if necessary to maintain rate limit
        """
        if self.max_rate <= 0:
            return

        with self._lock:
            current_time = time.perf_counter()
            time_since_last = current_time - self.last_operation_time

            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)

            self.last_operation_time = time.perf_counter()

    def can_proceed(self) -> bool:
        """
        Check if operation can proceed without sleeping

        Returns:
            True if enough time has passed since last operation
        """
        if self.max_rate <= 0:
            return True

        with self._lock:
            current_time = time.perf_counter()
            time_since_last = current_time - self.last_operation_time
            return time_since_last >= self.min_interval
