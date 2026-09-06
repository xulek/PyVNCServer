"""Reusable outbound/socket-pool primitives.

This module intentionally does not export a generic ``ConnectionPool`` name.
Server-side admission control is ``ConnectionLimiter``.
"""

from vnc_lib.connection_pool import (
    ReusableConnectionPool,
    ConnectionPoolManager,
    PooledConnection,
)

__all__ = ["ReusableConnectionPool", "ConnectionPoolManager", "PooledConnection"]
