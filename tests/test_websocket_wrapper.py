"""
Tests for WebSocket wrapper and adapter behavior.
"""

import socket
import struct

from vnc_lib.websocket_wrapper import (
    WebSocketOpcode,
    WebSocketWrapper,
    WebSocketVNCAdapter,
    is_websocket_request,
)


class FakeSocket:
    """Minimal fake socket for WebSocket unit tests."""

    def __init__(self, incoming: bytes = b''):
        self._incoming = bytearray(incoming)
        self.sent = bytearray()
        self._timeout = None
        self.closed = False

    def recv(self, n: int, flags: int = 0) -> bytes:
        if flags == socket.MSG_PEEK:
            return bytes(self._incoming[:n])
        if not self._incoming:
            return b''
        data = bytes(self._incoming[:n])
        del self._incoming[:n]
        return data

    def sendall(self, data: bytes):
        self.sent.extend(data)

    def settimeout(self, value):
        self._timeout = value

    def gettimeout(self):
        return self._timeout

    def close(self):
        self.closed = True

    def setsockopt(self, level, optname, value):
        return None


def _make_client_frame(opcode: int, payload: bytes, *, fin: bool = True,
                       masking_key: bytes = b"\x01\x02\x03\x04") -> bytes:
    """Build a masked client-to-server frame."""
    first = (0x80 if fin else 0x00) | (opcode & 0x0F)
    length = len(payload)
    frame = bytearray([first])

    if length <= 125:
        frame.append(0x80 | length)
    elif length <= 65535:
        frame.append(0x80 | 126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack(">Q", length))

    frame.extend(masking_key)
    masked = bytes(byte ^ masking_key[i % 4] for i, byte in enumerate(payload))
    frame.extend(masked)
    return bytes(frame)


def test_fragmented_binary_frames_are_reassembled():
    incoming = (
        _make_client_frame(WebSocketOpcode.BINARY, b"hel", fin=False)
        + _make_client_frame(WebSocketOpcode.CONTINUATION, b"lo", fin=True)
    )
    sock = FakeSocket(incoming)
    ws = WebSocketWrapper(sock)
    ws.handshake_complete = True

    assert ws.recv(1024) == b"hello"


def test_ping_frame_returns_empty_and_sends_pong():
    incoming = _make_client_frame(WebSocketOpcode.PING, b"abc", fin=True)
    sock = FakeSocket(incoming)
    ws = WebSocketWrapper(sock)
    ws.handshake_complete = True

    assert ws.recv(1024) == b""
    assert sock.sent[0] == (0x80 | WebSocketOpcode.PONG)
    assert sock.sent[1] == 3
    assert bytes(sock.sent[2:5]) == b"abc"


def test_websocket_payload_limit_is_enforced():
    oversized_len = 2048
    incoming = b"\x82" + b"\xfe" + struct.pack(">H", oversized_len)
    sock = FakeSocket(incoming)
    ws = WebSocketWrapper(sock, max_payload_bytes=1024)
    ws.handshake_complete = True

    assert ws.recv(1024) is None


def test_adapter_timeout_passthrough():
    sock = FakeSocket()
    adapter = WebSocketVNCAdapter(sock, do_handshake=False)

    adapter.settimeout(2.5)
    assert adapter.gettimeout() == 2.5


def test_is_websocket_request_restores_timeout():
    sock = FakeSocket(b"GET /websockify HTTP/1.1\r\n")
    sock.settimeout(9.0)

    assert is_websocket_request(sock, peek_timeout=0.05)
    assert sock.gettimeout() == 9.0
