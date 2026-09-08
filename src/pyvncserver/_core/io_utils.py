"""
Low-level I/O utilities for VNC socket operations.
"""

from typing import Optional


def recv_exact(sock, n: int) -> Optional[bytes]:
    """Receive exactly n bytes from socket.

    Returns None if the connection is closed before n bytes are received.
    """
    if n == 0:
        return b''
    buf = bytearray(n)
    view = memoryview(buf)
    total_received = 0
    while total_received < n:
        chunk = sock.recv(n - total_received)
        if not chunk:
            return None
        chunk_len = len(chunk)
        view[total_received:total_received + chunk_len] = chunk
        total_received += chunk_len
    return bytes(buf)
