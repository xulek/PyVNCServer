"""
RFB Protocol Handler - RFC 6143 Compliant
Handles protocol version negotiation, security, and message parsing
"""

import struct
import logging
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Iterable

from vnc_lib.exceptions import ConnectionError, ProtocolError
from vnc_lib.types import is_valid_pixel_format


@dataclass(slots=True)
class SecurityHandshakeResult:
    security_type: int
    auth_type: int
    needs_auth: bool
    tight_enabled: bool
    send_security_result_on_success: bool
    send_security_result_on_failure: bool


@dataclass(slots=True)
class TightCapability:
    code: int
    vendor_signature: bytes
    name_signature: bytes


class RFBProtocol:
    """Handles RFB protocol operations according to RFC 6143"""

    # Supported RFB versions (major, minor)
    SUPPORTED_VERSIONS = [
        (3, 3),   # RFB 003.003
        (3, 7),   # RFB 003.007
        (3, 8),   # RFB 003.008
    ]

    # Security types (RFC 6143 Section 7.1.2)
    SECURITY_NONE = 1
    SECURITY_VNC_AUTH = 2
    SECURITY_TIGHT = 16

    TIGHT_VENDOR_STANDARD = b"STDV"
    TIGHT_AUTH_SIG_VNC = b"VNCAUTH_"

    # Encoding types (RFC 6143 Section 7.7)
    ENCODING_RAW = 0
    ENCODING_COPYRECT = 1
    ENCODING_RRE = 2
    ENCODING_HEXTILE = 5
    ENCODING_TIGHT = 7          # Tight encoding (TightVNC extension)
    ENCODING_ZRLE = 16
    ENCODING_H264 = 50          # H.264 video encoding (custom extension)

    # Pseudo-encodings
    ENCODING_CURSOR = -239
    ENCODING_POINTER_POS = -232
    ENCODING_DESKTOP_SIZE = -223
    ENCODING_JPEG_QUALITY_LOW = -23   # JPEG quality level 0-9 (pseudo-encoding base -23 to -32)
    ENCODING_JPEG_QUALITY_HIGH = -32

    # Message types - Client to Server (RFC 6143 Section 7.5)
    MSG_SET_PIXEL_FORMAT = 0
    MSG_SET_ENCODINGS = 2
    MSG_FRAMEBUFFER_UPDATE_REQUEST = 3
    MSG_KEY_EVENT = 4
    MSG_POINTER_EVENT = 5
    MSG_CLIENT_CUT_TEXT = 6

    # Message types - Server to Client (RFC 6143 Section 7.6)
    MSG_FRAMEBUFFER_UPDATE = 0
    MSG_SET_COLOR_MAP_ENTRIES = 1
    MSG_BELL = 2
    MSG_SERVER_CUT_TEXT = 3

    DEFAULT_MAX_SET_ENCODINGS = 1024
    DEFAULT_MAX_CLIENT_CUT_TEXT = 16 * 1024 * 1024  # 16 MiB

    def __init__(self, max_set_encodings: int | None = None,
                 max_client_cut_text: int | None = None):
        self.version = (3, 8)  # Default to highest supported version
        self.logger = logging.getLogger(__name__)
        self.max_set_encodings = (
            max_set_encodings
            if max_set_encodings is not None
            else self.DEFAULT_MAX_SET_ENCODINGS
        )
        self.max_client_cut_text = (
            max_client_cut_text
            if max_client_cut_text is not None
            else self.DEFAULT_MAX_CLIENT_CUT_TEXT
        )

    def negotiate_version(self, client_socket) -> Tuple[int, int]:
        """
        Negotiate RFB protocol version with client (RFC 6143 Section 7.1.1)

        Returns: (major, minor) version tuple
        """
        # Send server's highest supported version
        server_version = b"RFB 003.008\n"
        client_socket.sendall(server_version)
        self.logger.info("Sent server version: RFB 003.008")

        # Receive client version
        client_version_data = self._recv_exact(client_socket, 12)
        if not client_version_data:
            raise ConnectionError("Failed to receive client version")

        # Parse client version
        try:
            version_str = client_version_data.decode('ascii').strip()
            if not version_str.startswith("RFB "):
                raise ValueError(f"Invalid version format: {version_str}")

            version_parts = version_str[4:].split('.')
            client_major = int(version_parts[0])
            client_minor = int(version_parts[1])

            self.logger.info(f"Client version: RFB {client_major:03d}.{client_minor:03d}")

            # Find the highest mutually supported version
            negotiated_version = self._find_common_version(client_major, client_minor)

            if negotiated_version:
                self.version = negotiated_version
                self.logger.info(f"Negotiated version: RFB {negotiated_version[0]:03d}.{negotiated_version[1]:03d}")
                return negotiated_version
            else:
                raise ValueError(f"No compatible version with client {client_major}.{client_minor}")

        except (ValueError, IndexError) as e:
            self.logger.error(f"Version negotiation failed: {e}")
            raise

    def _find_common_version(self, client_major: int, client_minor: int) -> Optional[Tuple[int, int]]:
        """Find the highest mutually supported version"""
        client_version = (client_major, client_minor)

        # Check if client version is in our supported list
        if client_version in self.SUPPORTED_VERSIONS:
            return client_version

        # Otherwise, find the highest version we both support
        # that is <= client version
        compatible = [
            v for v in self.SUPPORTED_VERSIONS
            if v[0] < client_major or (v[0] == client_major and v[1] <= client_minor)
        ]

        if compatible:
            return max(compatible)

        return None

    def negotiate_security(self, client_socket, password: Optional[str],
                           read_only_password: Optional[str] = None,
                           allow_tight_security: bool = True) -> SecurityHandshakeResult:
        """
        Negotiate security type (RFC 6143 Section 7.1.2)

        Returns a structured security handshake result.
        """
        has_vnc_auth = bool(password or read_only_password)
        primary_security_type = self.SECURITY_VNC_AUTH if has_vnc_auth else self.SECURITY_NONE

        if self.version >= (3, 7):
            security_types = [primary_security_type]
            if allow_tight_security:
                security_types.append(self.SECURITY_TIGHT)
            client_socket.sendall(struct.pack("B", len(security_types)))
            for st in security_types:
                client_socket.sendall(struct.pack("B", st))

            # Client selects security type
            selected = self._recv_exact(client_socket, 1)
            if not selected:
                raise ConnectionError("Client disconnected during security negotiation")

            selected_type = struct.unpack("B", selected)[0]
            if selected_type == self.SECURITY_TIGHT and allow_tight_security:
                return self._negotiate_tight_security(client_socket, has_vnc_auth)

            if selected_type != primary_security_type:
                self.logger.warning(f"Client selected unsupported security type: {selected_type}")
                # Send security result: failed
                client_socket.sendall(struct.pack(">I", 1))
                raise ConnectionError(
                    f"Client selected unsupported security type: {selected_type}"
                )

            self.logger.info(f"Security type negotiated: {primary_security_type}")
            return SecurityHandshakeResult(
                security_type=primary_security_type,
                auth_type=primary_security_type,
                needs_auth=primary_security_type == self.SECURITY_VNC_AUTH,
                tight_enabled=False,
                send_security_result_on_success=self.version >= (3, 8),
                send_security_result_on_failure=True,
            )
        else:
            # RFB 003.003: just send security type as 32-bit value
            client_socket.sendall(struct.pack(">I", primary_security_type))
            self.logger.info(f"Security type sent (RFB 003.003): {primary_security_type}")
            return SecurityHandshakeResult(
                security_type=primary_security_type,
                auth_type=primary_security_type,
                needs_auth=primary_security_type == self.SECURITY_VNC_AUTH,
                tight_enabled=False,
                send_security_result_on_success=self.version >= (3, 8),
                send_security_result_on_failure=True,
            )

    def _negotiate_tight_security(self, client_socket, has_vnc_auth: bool) -> SecurityHandshakeResult:
        """Perform TightVNC-style tunneling and auth-type negotiation."""
        client_socket.sendall(struct.pack(">I", 0))  # no tunneling

        if has_vnc_auth:
            auth_caps = (
                TightCapability(
                    code=self.SECURITY_VNC_AUTH,
                    vendor_signature=self.TIGHT_VENDOR_STANDARD,
                    name_signature=self.TIGHT_AUTH_SIG_VNC,
                ),
            )
            client_socket.sendall(struct.pack(">I", len(auth_caps)))
            self._send_tight_caps(client_socket, auth_caps)
            selected_auth = self._recv_exact(client_socket, 4)
            if not selected_auth:
                raise ConnectionError("Client disconnected during Tight auth negotiation")
            auth_type = struct.unpack(">I", selected_auth)[0]
            if auth_type != self.SECURITY_VNC_AUTH:
                client_socket.sendall(struct.pack(">I", 1))
                raise ConnectionError(
                    f"Client selected unsupported Tight auth type: {auth_type}"
                )
            self.logger.info("Security type negotiated: Tight (16) with VNC auth")
            return SecurityHandshakeResult(
                security_type=self.SECURITY_TIGHT,
                auth_type=self.SECURITY_VNC_AUTH,
                needs_auth=True,
                tight_enabled=True,
                send_security_result_on_success=True,
                send_security_result_on_failure=True,
            )

        client_socket.sendall(struct.pack(">I", 0))
        self.logger.info("Security type negotiated: Tight (16) with no auth")
        return SecurityHandshakeResult(
            security_type=self.SECURITY_TIGHT,
            auth_type=self.SECURITY_NONE,
            needs_auth=False,
            tight_enabled=True,
            send_security_result_on_success=self.version >= (3, 8),
            send_security_result_on_failure=True,
        )

    def _send_tight_caps(
        self, client_socket, caps: Iterable[TightCapability]
    ) -> None:
        for cap in caps:
            if len(cap.vendor_signature) != 4 or len(cap.name_signature) != 8:
                raise ProtocolError("Invalid Tight capability signature length")
            client_socket.sendall(struct.pack(">I", cap.code))
            client_socket.sendall(cap.vendor_signature)
            client_socket.sendall(cap.name_signature)

    def send_security_result(self, client_socket, success: bool):
        """Send security handshake result (RFC 6143 Section 7.1.3)"""
        result = 0 if success else 1
        client_socket.sendall(struct.pack(">I", result))

        # For RFB 003.008+, if failed, send reason string
        if not success and self.version >= (3, 8):
            reason = b"Authentication failed"
            client_socket.sendall(struct.pack(">I", len(reason)))
            client_socket.sendall(reason)

    def receive_client_init(self, client_socket) -> int:
        """Receive ClientInit message (RFC 6143 Section 7.3.1)"""
        shared_flag = self._recv_exact(client_socket, 1)
        if not shared_flag:
            raise ConnectionError("Failed to receive ClientInit")
        return struct.unpack("B", shared_flag)[0]

    def send_server_init(self, client_socket, width: int, height: int,
                        pixel_format: Dict, name: str):
        """Send ServerInit message (RFC 6143 Section 7.3.2)"""
        # Pack pixel format (16 bytes)
        pf_data = struct.pack(
            ">BBBBHHHBBB3x",
            pixel_format['bits_per_pixel'],
            pixel_format['depth'],
            pixel_format['big_endian_flag'],
            pixel_format['true_colour_flag'],
            pixel_format['red_max'],
            pixel_format['green_max'],
            pixel_format['blue_max'],
            pixel_format['red_shift'],
            pixel_format['green_shift'],
            pixel_format['blue_shift']
        )

        name_bytes = name.encode('latin-1')
        name_length = len(name_bytes)

        # Send: width, height, pixel_format, name_length, name
        msg = struct.pack(">HH", width, height) + pf_data + struct.pack(">I", name_length) + name_bytes
        client_socket.sendall(msg)
        self.logger.info(f"Sent ServerInit: {width}x{height}, name='{name}'")

    def send_tight_interaction_caps(
        self,
        client_socket,
        server_to_client: Iterable[TightCapability] = (),
        client_to_server: Iterable[TightCapability] = (),
        encoding_caps: Iterable[TightCapability] = (),
    ) -> None:
        server_to_client = tuple(server_to_client)
        client_to_server = tuple(client_to_server)
        encoding_caps = tuple(encoding_caps)
        client_socket.sendall(
            struct.pack(
                ">HHHH",
                len(server_to_client),
                len(client_to_server),
                len(encoding_caps),
                0,
            )
        )
        self._send_tight_caps(client_socket, server_to_client)
        self._send_tight_caps(client_socket, client_to_server)
        self._send_tight_caps(client_socket, encoding_caps)

    def parse_set_pixel_format(self, client_socket) -> Dict:
        """Parse SetPixelFormat message (RFC 6143 Section 7.5.1)"""
        # 3 bytes padding
        self._recv_exact(client_socket, 3)

        # 16 bytes pixel format
        pf_data = self._recv_exact(client_socket, 16)
        if not pf_data:
            raise ConnectionError("Failed to receive pixel format")

        pf = struct.unpack(">BBBBHHHBBB3x", pf_data)
        pixel_format = {
            'bits_per_pixel': pf[0],
            'depth': pf[1],
            'big_endian_flag': pf[2],
            'true_colour_flag': pf[3],
            'red_max': pf[4],
            'green_max': pf[5],
            'blue_max': pf[6],
            'red_shift': pf[7],
            'green_shift': pf[8],
            'blue_shift': pf[9]
        }

        self.logger.info(f"Client pixel format: {pixel_format['bits_per_pixel']}bpp, "
                        f"depth={pixel_format['depth']}, "
                        f"true_color={pixel_format['true_colour_flag']}")

        if not is_valid_pixel_format(pixel_format):
            raise ProtocolError(f"Unsupported or malformed pixel format: {pixel_format}")

        return pixel_format

    def parse_set_encodings(self, client_socket) -> list[int]:
        """
        Parse SetEncodings message (RFC 6143 Section 7.5.2)

        IMPORTANT: Encoding types are SIGNED 32-bit integers per RFC 6143
        """
        # 1 byte padding + 2 bytes number of encodings
        header = self._recv_exact(client_socket, 3)
        if not header:
            raise ConnectionError("Failed to receive SetEncodings header")

        _, num_encodings = struct.unpack(">BH", header)
        if num_encodings > self.max_set_encodings:
            raise ConnectionError(
                f"Too many encodings requested: {num_encodings} > {self.max_set_encodings}"
            )

        # Receive encoding types (SIGNED integers per RFC)
        enc_data = self._recv_exact(client_socket, 4 * num_encodings)
        if not enc_data:
            raise ConnectionError("Failed to receive encoding types")

        # Use 'i' (signed) not 'I' (unsigned) per RFC 6143.
        # Preserve the client's order because RFC 6143 defines it as a
        # preference hint; dedupe repeated values while keeping the first one.
        raw_encodings = struct.unpack(">" + "i" * num_encodings, enc_data)
        encodings: list[int] = []
        seen: set[int] = set()
        for enc in raw_encodings:
            if enc in seen:
                continue
            seen.add(enc)
            encodings.append(enc)

        self.logger.info(f"Client encodings: {encodings}")
        return encodings

    def parse_framebuffer_update_request(self, client_socket) -> Dict:
        """Parse FramebufferUpdateRequest (RFC 6143 Section 7.5.3)"""
        data = self._recv_exact(client_socket, 9)
        if not data:
            raise ConnectionError("Failed to receive FramebufferUpdateRequest")

        incremental, x, y, width, height = struct.unpack(">BHHHH", data)

        return {
            'incremental': incremental,
            'x': x,
            'y': y,
            'width': width,
            'height': height
        }

    def parse_key_event(self, client_socket) -> Dict:
        """Parse KeyEvent message (RFC 6143 Section 7.5.4)"""
        data = self._recv_exact(client_socket, 7)
        if not data:
            raise ConnectionError("Failed to receive KeyEvent")

        down_flag, _, key = struct.unpack(">BHI", data)

        return {
            'down_flag': down_flag,
            'key': key
        }

    def parse_pointer_event(self, client_socket) -> Dict:
        """Parse PointerEvent message (RFC 6143 Section 7.5.5)"""
        data = self._recv_exact(client_socket, 5)
        if not data:
            raise ConnectionError("Failed to receive PointerEvent")

        button_mask, x, y = struct.unpack(">BHH", data)

        return {
            'button_mask': button_mask,
            'x': x,
            'y': y
        }

    def parse_client_cut_text(self, client_socket) -> str:
        """Parse ClientCutText message (RFC 6143 Section 7.5.6)"""
        # 3 bytes padding
        self._recv_exact(client_socket, 3)

        # 4 bytes length
        length_data = self._recv_exact(client_socket, 4)
        if not length_data:
            raise ConnectionError("Failed to receive ClientCutText length")

        length = struct.unpack(">I", length_data)[0]
        if length > self.max_client_cut_text:
            raise ConnectionError(
                f"ClientCutText too large: {length} > {self.max_client_cut_text}"
            )

        # Receive text
        text_data = self._recv_exact(client_socket, length)
        if not text_data:
            raise ConnectionError("Failed to receive ClientCutText data")

        return text_data.decode('latin-1', errors='replace')

    def send_framebuffer_update(self, client_socket, rectangles: list):
        """
        Send FramebufferUpdate message (RFC 6143 Section 7.6.1)

        rectangles: list of (x, y, width, height, encoding, data) tuples
        """
        # Message type + padding + number of rectangles
        header = struct.pack(">BxH", self.MSG_FRAMEBUFFER_UPDATE, len(rectangles))

        # Calculate total size to decide whether to batch into single sendall
        total_data_size = sum(len(data) for _, _, _, _, _, data in rectangles if data)
        total_size = len(header) + len(rectangles) * 12 + total_data_size  # 12 = rect header size

        if total_size <= 1_048_576:  # Under 1MB: batch into single send
            parts = [header]
            for x, y, width, height, encoding, data in rectangles:
                parts.append(struct.pack(">HHHHi", x, y, width, height, encoding))
                if data:
                    parts.append(data if isinstance(data, (bytes, bytearray)) else bytes(data))
            client_socket.sendall(b"".join(parts))
        else:
            # Large update: send header then stream rectangle data
            client_socket.sendall(header)
            for x, y, width, height, encoding, data in rectangles:
                rect_header = struct.pack(">HHHHi", x, y, width, height, encoding)
                client_socket.sendall(rect_header)
                if data:
                    self._send_large_data(client_socket, data)

    def send_bell(self, client_socket):
        """Send Bell message (RFC 6143 Section 7.6.2)"""
        client_socket.sendall(struct.pack("B", self.MSG_BELL))

    def send_server_cut_text(self, client_socket, text: str):
        """Send ServerCutText message (RFC 6143 Section 7.6.3)"""
        text_bytes = text.encode('latin-1', errors='replace')
        msg = struct.pack(">BxxxI", self.MSG_SERVER_CUT_TEXT, len(text_bytes)) + text_bytes
        client_socket.sendall(msg)

    def _recv_exact(self, sock, n: int) -> Optional[bytes]:
        """Receive exactly n bytes from socket"""
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

    def _send_large_data(self, sock, data: bytes, chunk_size: int = 1048576):
        """Send large data in chunks using memoryview to avoid copies"""
        view = memoryview(data)
        total_sent = 0
        data_len = len(data)

        while total_sent < data_len:
            end = min(total_sent + chunk_size, data_len)
            sent = sock.send(view[total_sent:end])
            if sent == 0:
                raise ConnectionError("Socket connection broken during send")
            total_sent += sent
