"""
Low-level I/O utilities for VNC socket operations.
"""

from typing import Optional


def recv_exact(sock, n: int) -> Optional[bytes]:
    """Receive exactly *n* bytes with the minimum practical allocation count.

    Real sockets and ``ssl.SSLSocket`` expose ``recv_into``.  Using it writes
    directly into the destination bytearray and avoids allocating/copying one
    temporary ``bytes`` object for every partial TCP read.  Protocol adapters
    that only implement ``recv`` keep the compatibility path.
    """
    if n == 0:
        return b''
    if n < 0:
        raise ValueError("recv_exact length must not be negative")

    buf = bytearray(n)
    view = memoryview(buf)
    total_received = 0
    recv_into = getattr(sock, "recv_into", None)

    if callable(recv_into):
        while total_received < n:
            received = recv_into(view[total_received:])
            if not received:
                return None
            total_received += int(received)
        return bytes(buf)

    while total_received < n:
        chunk = sock.recv(n - total_received)
        if not chunk:
            return None
        chunk_len = len(chunk)
        view[total_received:total_received + chunk_len] = chunk
        total_received += chunk_len
    return bytes(buf)
