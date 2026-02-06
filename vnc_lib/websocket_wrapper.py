"""
WebSocket Wrapper for VNC Protocol
Enables browser-based VNC clients (noVNC) to connect to the VNC server
"""

import struct
import base64
import hashlib
import logging
import socket
from typing import Optional
from enum import IntEnum


class WebSocketOpcode(IntEnum):
    """WebSocket frame opcodes"""
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class WebSocketWrapper:
    """
    WebSocket protocol wrapper for VNC

    Wraps VNC protocol in WebSocket frames for browser compatibility.
    Compatible with noVNC (https://novnc.com/)

    Features:
    - RFC 6455 compliant WebSocket implementation
    - Binary frame support for VNC data
    - Automatic handshake handling
    - Frame masking/unmasking
    - Ping/Pong keepalive
    """

    MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455
    DEFAULT_MAX_HANDSHAKE_BYTES = 64 * 1024  # 64 KiB
    DEFAULT_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB

    def __init__(self, client_socket: socket.socket,
                 max_handshake_bytes: int = DEFAULT_MAX_HANDSHAKE_BYTES,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES):
        """
        Initialize WebSocket wrapper

        Args:
            client_socket: Raw TCP socket
        """
        self.socket = client_socket
        self.handshake_complete = False
        self.logger = logging.getLogger(__name__)
        self.max_handshake_bytes = max(1024, int(max_handshake_bytes))
        self.max_payload_bytes = max(1024, int(max_payload_bytes))
        self._fragment_buffer = bytearray()
        self._fragment_opcode: int | None = None

    def do_handshake(self) -> bool:
        """
        Perform WebSocket handshake (RFC 6455)

        Returns:
            True if handshake successful, False otherwise
        """
        try:
            # Read HTTP request
            request = bytearray()
            while b"\r\n\r\n" not in request:
                chunk = self.socket.recv(4096)
                if not chunk:
                    return False
                request.extend(chunk)
                if len(request) > self.max_handshake_bytes:
                    self.logger.warning(
                        f"WebSocket handshake exceeds max header size: "
                        f"{len(request)} > {self.max_handshake_bytes}"
                    )
                    return False

            # Parse request
            request_str = bytes(request).decode('utf-8', errors='ignore')
            request_line = request_str.split('\r\n', 1)[0]
            if not self._validate_request_line(request_line):
                self.logger.warning(f"Invalid WebSocket request line: {request_line!r}")
                return False
            headers = self._parse_headers(request_str)

            # Validate WebSocket request
            if not self._validate_handshake(headers):
                self.logger.warning("Invalid WebSocket handshake")
                return False

            # Get Sec-WebSocket-Key
            ws_key = headers.get('sec-websocket-key')
            if not ws_key:
                self.logger.error("Missing Sec-WebSocket-Key")
                return False

            # Calculate Sec-WebSocket-Accept
            accept_key = self._calculate_accept_key(ws_key)

            # Negotiate subprotocol (if any) according to RFC 6455:
            # Server may only send Sec-WebSocket-Protocol if the client
            # requested it, and the value must be one of the client's list.
            selected_protocol = None
            proto_header = headers.get('sec-websocket-protocol', '')
            if proto_header:
                # Client may send a comma-separated list, e.g. "binary, base64"
                for proto in proto_header.split(','):
                    p = proto.strip().lower()
                    if p in ('binary', 'base64'):
                        selected_protocol = p
                        break

            # Build handshake response
            lines = [
                "HTTP/1.1 101 Switching Protocols",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Accept: {accept_key}",
            ]
            if selected_protocol:
                lines.append(f"Sec-WebSocket-Protocol: {selected_protocol}")

            response = "\r\n".join(lines) + "\r\n\r\n"

            self.socket.sendall(response.encode('utf-8'))
            self.handshake_complete = True

            self.logger.info("WebSocket handshake completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"WebSocket handshake failed: {e}")
            return False

    def _validate_request_line(self, request_line: str) -> bool:
        """Validate HTTP request line for WebSocket upgrade."""
        parts = request_line.split()
        if len(parts) < 3:
            return False
        method, _path, version = parts[0], parts[1], parts[2]
        return method.upper() == 'GET' and version.upper().startswith('HTTP/')

    def _parse_headers(self, request: str) -> dict[str, str]:
        """Parse HTTP headers from request"""
        headers = {}
        lines = request.split('\r\n')

        for line in lines[1:]:  # Skip request line
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().lower()] = value.strip()

        return headers

    def _validate_handshake(self, headers: dict[str, str]) -> bool:
        """Validate WebSocket handshake request"""
        required_headers = {
            'upgrade': 'websocket',
            'connection': 'upgrade',
        }

        for key, expected_value in required_headers.items():
            actual_value = headers.get(key, '').lower()
            if expected_value not in actual_value:
                self.logger.warning(f"Invalid {key}: {actual_value}")
                return False

        if 'sec-websocket-key' not in headers:
            return False

        # RFC 6455 requires version 13. Keep compatibility with clients
        # that omit the header, but reject explicitly unsupported versions.
        version = headers.get('sec-websocket-version')
        if version and version.strip() != '13':
            self.logger.warning(f"Unsupported Sec-WebSocket-Version: {version}")
            return False

        return True

    def _calculate_accept_key(self, ws_key: str) -> str:
        """Calculate Sec-WebSocket-Accept key (RFC 6455)"""
        sha1 = hashlib.sha1()
        sha1.update((ws_key + self.MAGIC_STRING).encode('utf-8'))
        return base64.b64encode(sha1.digest()).decode('utf-8')

    def recv(self, size: int) -> Optional[bytes]:
        """
        Receive data from WebSocket (unwrap from frames)

        Args:
            size: Number of bytes to receive (may receive less)

        Returns:
            Unwrapped data or None on error
        """
        if not self.handshake_complete:
            self.logger.error("recv called before handshake")
            return None

        try:
            while True:
                # Read frame header
                header = self._recv_exact(2)
                if header is None:
                    return None

                # Parse frame
                byte1, byte2 = header[0], header[1]

                # Check FIN bit
                fin = (byte1 & 0x80) != 0

                # Get opcode
                opcode = byte1 & 0x0F

                # Check if masked
                masked = (byte2 & 0x80) != 0

                # Get payload length
                payload_len = byte2 & 0x7F

                # Extended payload length
                if payload_len == 126:
                    ext_len = self._recv_exact(2)
                    if ext_len is None:
                        return None
                    payload_len = struct.unpack(">H", ext_len)[0]
                elif payload_len == 127:
                    ext_len = self._recv_exact(8)
                    if ext_len is None:
                        return None
                    payload_len = struct.unpack(">Q", ext_len)[0]

                if payload_len > self.max_payload_bytes:
                    self.logger.warning(
                        f"WebSocket payload too large: {payload_len} > {self.max_payload_bytes}"
                    )
                    return None

                # Read masking key
                masking_key = None
                if masked:
                    masking_key = self._recv_exact(4)
                    if masking_key is None:
                        return None

                # Read payload
                payload = self._recv_exact(payload_len)
                if payload is None:
                    return None

                # Unmask if needed
                if masked and masking_key:
                    payload = self._unmask(payload, masking_key)

                # Handle control frames
                if opcode == WebSocketOpcode.CLOSE:
                    self.logger.info("WebSocket close frame received")
                    return None
                if opcode == WebSocketOpcode.PING:
                    self._send_pong(payload)
                    return b''  # Return empty to continue
                if opcode == WebSocketOpcode.PONG:
                    return b''  # Ignore pong

                if opcode == WebSocketOpcode.CONTINUATION:
                    if self._fragment_opcode is None:
                        # Broken client: continuation without a start frame.
                        self.logger.warning("WebSocket continuation frame without active fragment")
                        if fin:
                            return payload
                        self._fragment_opcode = WebSocketOpcode.BINARY
                        self._fragment_buffer = bytearray(payload)
                        continue

                    self._fragment_buffer.extend(payload)
                    if fin:
                        message = bytes(self._fragment_buffer)
                        self._fragment_buffer.clear()
                        self._fragment_opcode = None
                        return message
                    continue

                if opcode not in (WebSocketOpcode.BINARY, WebSocketOpcode.TEXT):
                    self.logger.warning(f"Unsupported WebSocket opcode: 0x{opcode:02x}")
                    self._fragment_buffer.clear()
                    self._fragment_opcode = None
                    return None

                if opcode == WebSocketOpcode.TEXT:
                    self.logger.warning("Received text frame, expected binary")

                if self._fragment_opcode is not None:
                    self.logger.warning(
                        "WebSocket fragment stream reset due to unexpected new data frame"
                    )
                    self._fragment_buffer.clear()
                    self._fragment_opcode = None

                if fin:
                    return payload

                # Start of fragmented message.
                self._fragment_opcode = opcode
                self._fragment_buffer = bytearray(payload)

        except Exception as e:
            self.logger.error(f"Error receiving WebSocket data: {e}")
            return None

    def send(self, data: bytes) -> int:
        """
        Send data over WebSocket (wrap in frames)

        Args:
            data: Data to send

        Returns:
            Number of bytes sent (wrapped data)
        """
        if not self.handshake_complete:
            self.logger.error("send called before handshake")
            return 0

        try:
            frame = self._create_frame(data, WebSocketOpcode.BINARY)
            self.socket.sendall(frame)
            return len(data)  # Return original data length

        except Exception as e:
            self.logger.error(f"Error sending WebSocket data: {e}")
            return 0

    def sendall(self, data: bytes):
        """Send all data (alias for send)"""
        self.send(data)

    def _create_frame(self, payload: bytes, opcode: int) -> bytes:
        """
        Create WebSocket frame

        Args:
            payload: Frame payload
            opcode: Frame opcode

        Returns:
            Complete frame
        """
        frame = bytearray()

        # First byte: FIN=1, RSV=000, Opcode
        frame.append(0x80 | opcode)

        # Payload length
        payload_len = len(payload)

        if payload_len <= 125:
            # Mask=0, Length
            frame.append(payload_len)
        elif payload_len <= 65535:
            # Mask=0, Length=126
            frame.append(126)
            frame.extend(struct.pack(">H", payload_len))
        else:
            # Mask=0, Length=127
            frame.append(127)
            frame.extend(struct.pack(">Q", payload_len))

        # Server frames are not masked (only client->server frames are masked)
        frame.extend(payload)

        return bytes(frame)

    def _send_pong(self, data: bytes):
        """Send pong frame in response to ping"""
        frame = self._create_frame(data, WebSocketOpcode.PONG)
        self.socket.sendall(frame)
        self.logger.debug("Sent pong frame")

    def _unmask(self, payload: bytes, masking_key: bytes) -> bytes:
        """Unmask WebSocket payload"""
        unmasked = bytearray()
        for i, byte in enumerate(payload):
            unmasked.append(byte ^ masking_key[i % 4])
        return bytes(unmasked)

    def _recv_exact(self, n: int) -> Optional[bytes]:
        """Receive exactly n bytes"""
        if n == 0:
            return b''
        buf = bytearray()
        while len(buf) < n:
            chunk = self.socket.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def close(self):
        """Close WebSocket connection"""
        if self.handshake_complete:
            try:
                # Send close frame
                close_frame = self._create_frame(b'', WebSocketOpcode.CLOSE)
                self.socket.sendall(close_frame)
            except:
                pass

        try:
            self.socket.close()
        except:
            pass

        self.logger.info("WebSocket connection closed")


class WebSocketVNCAdapter:
    """
    Adapter to make WebSocket wrapper compatible with VNC protocol handler

    Provides same interface as regular socket for transparent integration
    """

    def __init__(self, client_socket: socket.socket, do_handshake: bool = True,
                 max_handshake_bytes: int = WebSocketWrapper.DEFAULT_MAX_HANDSHAKE_BYTES,
                 max_payload_bytes: int = WebSocketWrapper.DEFAULT_MAX_PAYLOAD_BYTES,
                 max_buffer_bytes: int = 16 * 1024 * 1024):
        """
        Initialize WebSocket VNC adapter

        Args:
            client_socket: Raw TCP socket
            do_handshake: Perform handshake immediately
        """
        self.ws = WebSocketWrapper(
            client_socket,
            max_handshake_bytes=max_handshake_bytes,
            max_payload_bytes=max_payload_bytes,
        )
        self.logger = logging.getLogger(__name__)
        self.recv_buffer = bytearray()
        self.max_buffer_bytes = max(4096, int(max_buffer_bytes))

        if do_handshake:
            if not self.ws.do_handshake():
                raise ConnectionError("WebSocket handshake failed")

    def recv(self, size: int) -> bytes:
        """Receive data (socket-compatible interface)"""
        # Try to fill buffer
        while len(self.recv_buffer) < size:
            data = self.ws.recv(size)
            if data is None:
                break
            if len(data) > 0:  # Skip empty frames (ping/pong)
                if len(self.recv_buffer) + len(data) > self.max_buffer_bytes:
                    raise ConnectionError(
                        f"WebSocket receive buffer exceeded limit: "
                        f"{len(self.recv_buffer) + len(data)} > {self.max_buffer_bytes}"
                    )
                self.recv_buffer.extend(data)

        # Return requested amount
        result = bytes(self.recv_buffer[:size])
        self.recv_buffer = self.recv_buffer[size:]
        return result

    def send(self, data: bytes) -> int:
        """Send data (socket-compatible interface)"""
        return self.ws.send(data)

    def sendall(self, data: bytes):
        """Send all data (socket-compatible interface)"""
        self.ws.sendall(data)

    def close(self):
        """Close connection (socket-compatible interface)"""
        self.ws.close()

    def setsockopt(self, level, optname, value):
        """Socket option setter (pass-through)"""
        try:
            self.ws.socket.setsockopt(level, optname, value)
        except:
            pass  # Ignore errors for WebSocket

    def settimeout(self, value):
        """Socket timeout setter (pass-through)."""
        self.ws.socket.settimeout(value)

    def gettimeout(self):
        """Socket timeout getter (pass-through)."""
        return self.ws.socket.gettimeout()


def is_websocket_request(client_socket: socket.socket, peek_timeout: float = 0.5) -> bool:
    """
    Check if incoming connection is WebSocket request

    Peeks at first bytes to detect HTTP/WebSocket handshake

    Args:
        client_socket: Client socket

    Returns:
        True if WebSocket request detected
    """
    original_timeout = None
    try:
        # Set a short timeout for the peek
        original_timeout = client_socket.gettimeout()
        client_socket.settimeout(peek_timeout)

        # Peek at first bytes without consuming them
        # Note: MSG_PEEK may not work reliably on all platforms
        first_bytes = client_socket.recv(16, socket.MSG_PEEK)

        if not first_bytes:
            return False

        # Check for HTTP request (GET for WebSocket upgrade)
        # VNC starts with "RFB " (0x52 0x46 0x42 0x20)
        # HTTP starts with "GET " (0x47 0x45 0x54 0x20)
        return first_bytes.startswith(b'GET ') or first_bytes.startswith(b'get ')

    except socket.timeout:
        # Timeout means no data available yet - not a WebSocket
        return False
    except Exception:
        # On error, assume not WebSocket (better to fail open for VNC clients)
        return False
    finally:
        if original_timeout is not None:
            try:
                client_socket.settimeout(original_timeout)
            except Exception:
                pass
