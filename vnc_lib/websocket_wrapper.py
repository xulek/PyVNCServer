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

    def __init__(self, client_socket: socket.socket):
        """
        Initialize WebSocket wrapper

        Args:
            client_socket: Raw TCP socket
        """
        self.socket = client_socket
        self.handshake_complete = False
        self.logger = logging.getLogger(__name__)

    def do_handshake(self) -> bool:
        """
        Perform WebSocket handshake (RFC 6455)

        Returns:
            True if handshake successful, False otherwise
        """
        try:
            # Read HTTP request
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = self.socket.recv(4096)
                if not chunk:
                    return False
                request += chunk

            # Parse request
            request_str = request.decode('utf-8', errors='ignore')
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
            # Read frame header
            header = self._recv_exact(2)
            if not header:
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
                if not ext_len:
                    return None
                payload_len = struct.unpack(">H", ext_len)[0]
            elif payload_len == 127:
                ext_len = self._recv_exact(8)
                if not ext_len:
                    return None
                payload_len = struct.unpack(">Q", ext_len)[0]

            # Read masking key
            masking_key = None
            if masked:
                masking_key = self._recv_exact(4)
                if not masking_key:
                    return None

            # Read payload
            payload = self._recv_exact(payload_len)
            if not payload:
                return None

            # Unmask if needed
            if masked and masking_key:
                payload = self._unmask(payload, masking_key)

            # Handle control frames
            if opcode == WebSocketOpcode.CLOSE:
                self.logger.info("WebSocket close frame received")
                return None
            elif opcode == WebSocketOpcode.PING:
                self._send_pong(payload)
                return b''  # Return empty to continue
            elif opcode == WebSocketOpcode.PONG:
                return b''  # Ignore pong

            # Return binary payload
            if opcode == WebSocketOpcode.BINARY or opcode == WebSocketOpcode.CONTINUATION:
                return payload

            # Text frame - shouldn't happen for VNC
            if opcode == WebSocketOpcode.TEXT:
                self.logger.warning("Received text frame, expected binary")
                return payload.encode('utf-8') if isinstance(payload, str) else payload

            return None

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
        buf = b''
        while len(buf) < n:
            chunk = self.socket.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

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

    def __init__(self, client_socket: socket.socket, do_handshake: bool = True):
        """
        Initialize WebSocket VNC adapter

        Args:
            client_socket: Raw TCP socket
            do_handshake: Perform handshake immediately
        """
        self.ws = WebSocketWrapper(client_socket)
        self.logger = logging.getLogger(__name__)
        self.recv_buffer = bytearray()

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


def is_websocket_request(client_socket: socket.socket) -> bool:
    """
    Check if incoming connection is WebSocket request

    Peeks at first bytes to detect HTTP/WebSocket handshake

    Args:
        client_socket: Client socket

    Returns:
        True if WebSocket request detected
    """
    try:
        # Set a short timeout for the peek
        original_timeout = client_socket.gettimeout()
        client_socket.settimeout(0.1)  # 100ms timeout

        # Peek at first bytes without consuming them
        # Note: MSG_PEEK may not work reliably on all platforms
        first_bytes = client_socket.recv(16, socket.MSG_PEEK)

        # Restore original timeout
        client_socket.settimeout(original_timeout)

        if not first_bytes:
            return False

        # Check for HTTP request (GET for WebSocket upgrade)
        # VNC starts with "RFB " (0x52 0x46 0x42 0x20)
        # HTTP starts with "GET " (0x47 0x45 0x54 0x20)
        return first_bytes.startswith(b'GET ') or first_bytes.startswith(b'get ')

    except socket.timeout:
        # Timeout means no data available yet - not a WebSocket
        return False
    except Exception as e:
        # On error, assume not WebSocket (better to fail open for VNC clients)
        return False
