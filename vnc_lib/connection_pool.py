"""
Connection Pool Module

Advanced connection pooling with resource management, health checks, and graceful degradation.
Uses Python 3.13 features for better performance and type safety.

Uses Python 3.13 features:
- Type parameter syntax
- Pattern matching
- Exception groups
- Better threading utilities
"""

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol, Self
from collections.abc import Callable
from enum import IntEnum, auto
from queue import Queue, Empty, Full


class ConnectionState(IntEnum):
    """Connection lifecycle states."""

    IDLE = auto()
    ACTIVE = auto()
    CLOSING = auto()
    CLOSED = auto()
    ERROR = auto()


@dataclass(slots=True)
class ConnectionMetrics:
    """Metrics for a pooled connection."""

    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    total_requests: int = 0
    total_bytes_sent: int = 0
    total_bytes_received: int = 0
    error_count: int = 0

    def update_usage(self) -> None:
        """Update last used timestamp."""
        self.last_used = time.time()

    def increment_request(self) -> None:
        """Increment request counter."""
        self.total_requests += 1

    def add_bytes_sent(self, count: int) -> None:
        """Add to bytes sent counter."""
        self.total_bytes_sent += count

    def add_bytes_received(self, count: int) -> None:
        """Add to bytes received counter."""
        self.total_bytes_received += count

    def increment_error(self) -> None:
        """Increment error counter."""
        self.error_count += 1

    @property
    def age(self) -> float:
        """Get connection age in seconds."""
        return time.time() - self.created_at

    @property
    def idle_time(self) -> float:
        """Get idle time in seconds."""
        return time.time() - self.last_used


@dataclass(slots=True)
class PooledConnection:
    """Represents a pooled network connection with lifecycle management."""

    connection: socket.socket
    connection_id: str
    state: ConnectionState = ConnectionState.IDLE
    metrics: ConnectionMetrics = field(default_factory=ConnectionMetrics)
    user_data: dict = field(default_factory=dict)

    def mark_active(self) -> None:
        """Mark connection as active."""
        self.state = ConnectionState.ACTIVE
        self.metrics.update_usage()
        self.metrics.increment_request()

    def mark_idle(self) -> None:
        """Mark connection as idle."""
        self.state = ConnectionState.IDLE
        self.metrics.update_usage()

    def mark_error(self) -> None:
        """Mark connection as errored."""
        self.state = ConnectionState.ERROR
        self.metrics.increment_error()

    def close(self) -> None:
        """Close the connection."""
        if self.state != ConnectionState.CLOSED:
            self.state = ConnectionState.CLOSING
            try:
                self.connection.close()
            except Exception:
                pass
            finally:
                self.state = ConnectionState.CLOSED

    @property
    def is_healthy(self) -> bool:
        """Check if connection is in a healthy state."""
        return self.state in (ConnectionState.IDLE, ConnectionState.ACTIVE)

    @property
    def is_active(self) -> bool:
        """Check if connection is currently active."""
        return self.state == ConnectionState.ACTIVE

    @property
    def is_idle(self) -> bool:
        """Check if connection is idle."""
        return self.state == ConnectionState.IDLE


class ConnectionPool:
    """
    Thread-safe connection pool with health monitoring and resource limits.

    Features:
    - Configurable pool size limits
    - Automatic connection recycling
    - Health checks
    - Connection timeout
    - Graceful shutdown
    - Detailed metrics
    """

    __slots__ = ('_pool', '_active', '_max_size', '_min_size', '_max_idle_time',
                 '_max_connection_age', '_lock', '_connection_counter',
                 '_pool_closed', '_health_check_fn')

    def __init__(
        self,
        max_size: int = 100,
        min_size: int = 0,
        max_idle_time: float = 300.0,  # 5 minutes
        max_connection_age: float = 3600.0,  # 1 hour
        health_check: Callable[[socket.socket], bool] | None = None
    ):
        self._pool: Queue[PooledConnection] = Queue(maxsize=max_size)
        self._active: dict[str, PooledConnection] = {}
        self._max_size = max_size
        self._min_size = min_size
        self._max_idle_time = max_idle_time
        self._max_connection_age = max_connection_age
        self._lock = threading.RLock()
        self._connection_counter = 0
        self._pool_closed = False
        self._health_check_fn = health_check

    def add_connection(self, connection: socket.socket) -> PooledConnection:
        """
        Add a new connection to the pool.

        Returns:
            PooledConnection object
        """
        if self._pool_closed:
            raise RuntimeError("Connection pool is closed")

        with self._lock:
            # Generate unique connection ID
            self._connection_counter += 1
            conn_id = f"conn-{self._connection_counter}"

            pooled_conn = PooledConnection(
                connection=connection,
                connection_id=conn_id,
                state=ConnectionState.IDLE
            )

            try:
                self._pool.put_nowait(pooled_conn)
                return pooled_conn
            except Full:
                # Pool is full, close the connection
                connection.close()
                raise RuntimeError("Connection pool is full")

    def acquire(self, timeout: float | None = None) -> PooledConnection | None:
        """
        Acquire a connection from the pool.

        Args:
            timeout: Maximum time to wait for a connection (None = wait forever)

        Returns:
            PooledConnection or None if timeout
        """
        if self._pool_closed:
            raise RuntimeError("Connection pool is closed")

        try:
            # Try to get connection from pool
            pooled_conn = self._pool.get(timeout=timeout)

            # Check if connection is healthy
            if not self._is_connection_valid(pooled_conn):
                pooled_conn.close()
                return None

            # Mark as active
            pooled_conn.mark_active()

            with self._lock:
                self._active[pooled_conn.connection_id] = pooled_conn

            return pooled_conn

        except Empty:
            return None

    def release(self, pooled_conn: PooledConnection, reuse: bool = True) -> None:
        """
        Release a connection back to the pool.

        Args:
            pooled_conn: Connection to release
            reuse: Whether to reuse the connection (False = close it)
        """
        if self._pool_closed:
            pooled_conn.close()
            return

        with self._lock:
            # Remove from active connections
            self._active.pop(pooled_conn.connection_id, None)

        if not reuse or not self._is_connection_valid(pooled_conn):
            pooled_conn.close()
            return

        # Mark as idle and return to pool
        pooled_conn.mark_idle()

        try:
            self._pool.put_nowait(pooled_conn)
        except Full:
            # Pool is full, close the connection
            pooled_conn.close()

    def _is_connection_valid(self, pooled_conn: PooledConnection) -> bool:
        """Check if a connection is still valid and healthy."""
        # Check state
        if not pooled_conn.is_healthy:
            return False

        # Check if too old
        if pooled_conn.metrics.age > self._max_connection_age:
            return False

        # Check if idle too long
        if pooled_conn.metrics.idle_time > self._max_idle_time:
            return False

        # Run custom health check if provided
        if self._health_check_fn:
            try:
                if not self._health_check_fn(pooled_conn.connection):
                    return False
            except Exception:
                return False

        return True

    def cleanup_idle_connections(self) -> int:
        """
        Remove idle and stale connections from the pool.

        Returns:
            Number of connections removed
        """
        removed_count = 0

        # Get all connections from pool
        connections_to_check = []
        while True:
            try:
                conn = self._pool.get_nowait()
                connections_to_check.append(conn)
            except Empty:
                break

        # Check each connection
        for conn in connections_to_check:
            if self._is_connection_valid(conn):
                # Return valid connections to pool
                try:
                    self._pool.put_nowait(conn)
                except Full:
                    conn.close()
                    removed_count += 1
            else:
                # Close invalid connections
                conn.close()
                removed_count += 1

        return removed_count

    def close_all(self) -> None:
        """Close all connections in the pool."""
        self._pool_closed = True

        # Close all idle connections
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break

        # Close all active connections
        with self._lock:
            for conn in self._active.values():
                conn.close()
            self._active.clear()

    def get_stats(self) -> dict[str, int | float]:
        """Get pool statistics."""
        with self._lock:
            active_count = len(self._active)
            idle_count = self._pool.qsize()

            total_requests = 0
            total_bytes_sent = 0
            total_bytes_received = 0
            total_errors = 0

            # Aggregate metrics from active connections
            for conn in self._active.values():
                total_requests += conn.metrics.total_requests
                total_bytes_sent += conn.metrics.total_bytes_sent
                total_bytes_received += conn.metrics.total_bytes_received
                total_errors += conn.metrics.error_count

            return {
                'active_connections': active_count,
                'idle_connections': idle_count,
                'total_connections': active_count + idle_count,
                'max_size': self._max_size,
                'min_size': self._min_size,
                'total_requests': total_requests,
                'total_bytes_sent': total_bytes_sent,
                'total_bytes_received': total_bytes_received,
                'total_errors': total_errors,
                'pool_closed': self._pool_closed
            }

    @property
    def is_closed(self) -> bool:
        """Check if pool is closed."""
        return self._pool_closed

    @property
    def active_count(self) -> int:
        """Get number of active connections."""
        with self._lock:
            return len(self._active)

    @property
    def idle_count(self) -> int:
        """Get number of idle connections."""
        return self._pool.qsize()

    @property
    def total_count(self) -> int:
        """Get total number of connections."""
        return self.active_count + self.idle_count

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        self.close_all()
        return False


class ConnectionPoolManager:
    """
    Manages multiple connection pools with automatic cleanup and monitoring.

    Runs a background thread to clean up idle connections periodically.
    """

    __slots__ = ('_pools', '_lock', '_cleanup_thread', '_cleanup_interval',
                 '_running', '_stats')

    def __init__(self, cleanup_interval: float = 60.0):
        self._pools: dict[str, ConnectionPool] = {}
        self._lock = threading.RLock()
        self._cleanup_thread: threading.Thread | None = None
        self._cleanup_interval = cleanup_interval
        self._running = False
        self._stats = {
            'total_cleanups': 0,
            'total_connections_removed': 0
        }

    def create_pool(
        self,
        name: str,
        max_size: int = 100,
        min_size: int = 0,
        **kwargs
    ) -> ConnectionPool:
        """Create a new connection pool."""
        with self._lock:
            if name in self._pools:
                raise ValueError(f"Pool '{name}' already exists")

            pool = ConnectionPool(max_size=max_size, min_size=min_size, **kwargs)
            self._pools[name] = pool
            return pool

    def get_pool(self, name: str) -> ConnectionPool | None:
        """Get a pool by name."""
        with self._lock:
            return self._pools.get(name)

    def remove_pool(self, name: str) -> None:
        """Remove and close a pool."""
        with self._lock:
            pool = self._pools.pop(name, None)
            if pool:
                pool.close_all()

    def start_cleanup(self) -> None:
        """Start the background cleanup thread."""
        if self._running:
            return

        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="connection-pool-cleanup"
        )
        self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        """Stop the background cleanup thread."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5.0)
            self._cleanup_thread = None

    def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        while self._running:
            time.sleep(self._cleanup_interval)

            with self._lock:
                total_removed = 0
                for pool in self._pools.values():
                    removed = pool.cleanup_idle_connections()
                    total_removed += removed

                if total_removed > 0:
                    self._stats['total_cleanups'] += 1
                    self._stats['total_connections_removed'] += total_removed

    def close_all_pools(self) -> None:
        """Close all connection pools."""
        with self._lock:
            for pool in self._pools.values():
                pool.close_all()
            self._pools.clear()

    def get_stats(self) -> dict[str, dict | int]:
        """Get statistics for all pools."""
        with self._lock:
            pool_stats = {
                name: pool.get_stats()
                for name, pool in self._pools.items()
            }

            return {
                'pools': pool_stats,
                'pool_count': len(self._pools),
                'manager_stats': self._stats.copy()
            }

    def __enter__(self) -> Self:
        """Context manager entry."""
        self.start_cleanup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        self.stop_cleanup()
        self.close_all_pools()
        return False
