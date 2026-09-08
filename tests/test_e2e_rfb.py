"""End-to-end loopback RFB smoke test for the real server session path."""

from __future__ import annotations

import socket
import struct
import threading

from pyvncserver.app import server as server_module
from pyvncserver._core.capture_backends import CaptureBackendCapabilities, CaptureFrame, CaptureMetadata
from pyvncserver._core.screen_capture import CaptureResult


class _FakeCapture:
    def __init__(self, scale_factor=1.0, monitor=0, backend_preference="auto"):
        self.scale_factor = scale_factor
        self.monitor = monitor
        self.backend_preference = backend_preference
        self._backend = self
        self._pixels = bytes([
            0, 0, 255, 0,
            0, 255, 0, 0,
            255, 0, 0, 0,
            255, 255, 255, 0,
        ])

    def set_cache_frame_rate(self, _fps):
        return None

    def get_backend_name(self):
        return "fake"

    def get_backend_capabilities(self):
        return CaptureBackendCapabilities(
            name="fake",
            supports_bgra=True,
            supports_rgb=True,
            supports_pil_image=False,
            supports_dirty_regions=True,
            supports_move_rects=False,
        )

    def healthcheck(self):
        return True

    def capture_frame(self, _pixel_format):
        return CaptureFrame(
            result=CaptureResult(self._pixels, None, 2, 2, 0.0001),
            metadata=CaptureMetadata(
                backend_name="fake",
                dirty_regions=[(0, 0, 2, 2)],
                move_rects=[],
                supports_dirty_regions=True,
                supports_move_rects=False,
            ),
        )

    def capture_fast(self, pixel_format):
        return self.capture_frame(pixel_format).result

    def convert_native_bgr0(self, pixel_data, _width, _height, _pixel_format):
        return pixel_data

    def close_current_thread_sessions(self):
        return None


class _ResizingFakeCapture(_FakeCapture):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._captures = 0

    def capture_frame(self, _pixel_format):
        self._captures += 1
        if self._captures == 1:
            width, height = 2, 2
        else:
            width, height = 3, 2
        pixels = bytes([0, 0, 0, 0]) * (width * height)
        return CaptureFrame(
            result=CaptureResult(pixels, None, width, height, 0.0001),
            metadata=CaptureMetadata(
                backend_name="fake",
                dirty_regions=[(0, 0, width, height)],
                move_rects=[],
                supports_dirty_regions=True,
                supports_move_rects=False,
            ),
        )


class _FakeInputHandler:
    def __init__(self, scale_factor=1.0):
        self.scale_factor = scale_factor

    def handle_pointer_event(self, *_args, **_kwargs):
        return None

    def handle_key_event(self, *_args, **_kwargs):
        return None


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise AssertionError(f"connection closed after {len(chunks)}/{size} bytes")
        chunks.extend(chunk)
    return bytes(chunks)


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_real_server_completes_handshake_and_raw_frame_update(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "ScreenCapture", _FakeCapture)
    monkeypatch.setattr(server_module, "InputHandler", _FakeInputHandler)

    port = _free_tcp_port()
    config = tmp_path / "server.toml"
    config.write_text(
        f'''[server]\nhost = "127.0.0.1"\nport = {port}\nframe_rate = 30\nlan_frame_rate = 30\nnetwork_profile_override = "auto"\nmax_connections = 2\nmax_connections_per_ip = 2\nmax_unauthenticated_connections = 2\nhandshake_timeout = 2.0\nclient_socket_timeout = 2.0\n\n[features]\nenable_metrics = false\nenable_health_checks = false\nenable_capture_producer = false\nenable_parallel_encoding = false\nenable_region_detection = false\nenable_websocket = false\nenable_tight_extensions = false\nenable_tight_encoding = false\nenable_jpeg_encoding = false\nenable_zrle_encoding = false\nenable_copyrect_encoding = false\n''',
        encoding="utf-8",
    )

    server = server_module.VNCServerV3(config)
    thread = threading.Thread(target=server.start, name="test-vnc-server")
    thread.start()

    client = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    client.settimeout(2.0)
    try:
        version = _recv_exact(client, 12)
        assert version == b"RFB 003.008\n"
        client.sendall(version)

        count = _recv_exact(client, 1)[0]
        security_types = _recv_exact(client, count)
        assert 1 in security_types
        client.sendall(b"\x01")
        assert _recv_exact(client, 4) == b"\x00\x00\x00\x00"

        client.sendall(b"\x01")
        width, height = struct.unpack(">HH", _recv_exact(client, 4))
        assert (width, height) == (2, 2)
        _recv_exact(client, 16)
        name_length = struct.unpack(">I", _recv_exact(client, 4))[0]
        assert b"PyVNCServer" in _recv_exact(client, name_length)

        client.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, 2, 2))
        message_type, rectangle_count = struct.unpack(">BxH", _recv_exact(client, 4))
        assert message_type == 0
        assert rectangle_count >= 1

        x, y, rw, rh, encoding = struct.unpack(">HHHHi", _recv_exact(client, 12))
        assert (x, y, rw, rh, encoding) == (0, 0, 2, 2, 0)
        assert len(_recv_exact(client, rw * rh * 4)) == 16
    finally:
        client.close()
        server.shutdown_handler.shutdown()
        thread.join(timeout=5.0)
        assert not thread.is_alive()


def test_real_server_continuous_updates_and_fence(tmp_path, monkeypatch):
    """noVNC-style ContinuousUpdates/Fence negotiation works over real TCP."""
    monkeypatch.setattr(server_module, "ScreenCapture", _FakeCapture)
    monkeypatch.setattr(server_module, "InputHandler", _FakeInputHandler)

    port = _free_tcp_port()
    config = tmp_path / "server-modern-rfb.toml"
    config.write_text(
        f"""[server]
host = "127.0.0.1"
port = {port}
frame_rate = 30
lan_frame_rate = 30
network_profile_override = "auto"
max_connections = 2
max_connections_per_ip = 2
max_unauthenticated_connections = 2
handshake_timeout = 2.0
client_socket_timeout = 2.0

[features]
enable_metrics = false
enable_health_checks = false
enable_capture_producer = false
enable_parallel_encoding = false
enable_region_detection = false
enable_websocket = false
enable_tight_extensions = false
enable_tight_encoding = false
enable_jpeg_encoding = false
enable_zrle_encoding = false
enable_copyrect_encoding = false
enable_continuous_updates = true
enable_fence = true
enable_last_rect = false
enable_extended_desktop_size = true
""",
        encoding="utf-8",
    )

    server = server_module.VNCServerV3(config)
    thread = threading.Thread(target=server.start, name="test-vnc-modern-rfb")
    thread.start()

    client = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    client.settimeout(2.0)
    try:
        version = _recv_exact(client, 12)
        client.sendall(version)
        count = _recv_exact(client, 1)[0]
        security_types = _recv_exact(client, count)
        assert 1 in security_types
        client.sendall(b"\x01")
        assert _recv_exact(client, 4) == b"\x00\x00\x00\x00"
        client.sendall(b"\x01")
        _recv_exact(client, 4 + 16)
        name_length = struct.unpack(">I", _recv_exact(client, 4))[0]
        _recv_exact(client, name_length)

        encodings = (0, -312, -313)
        client.sendall(
            struct.pack(">BBH", 2, 0, len(encodings))
            + struct.pack(">" + "i" * len(encodings), *encodings)
        )

        assert _recv_exact(client, 1) == b"\x96"

        assert _recv_exact(client, 1) == b"\xf8"
        padding_flags_len = _recv_exact(client, 8)
        _padding, flags, payload_len = struct.unpack(">3sIB", padding_flags_len)
        assert flags & (1 << 31)
        payload = _recv_exact(client, payload_len)
        client.sendall(
            struct.pack(">BxxxIB", 248, flags & ~(1 << 31), payload_len)
            + payload
        )

        client.sendall(struct.pack(">BBHHHH", 150, 1, 0, 0, 2, 2))

        message_type, rectangle_count = struct.unpack(">BxH", _recv_exact(client, 4))
        assert message_type == 0
        assert rectangle_count >= 1
        x, y, rw, rh, encoding = struct.unpack(">HHHHi", _recv_exact(client, 12))
        assert (x, y, rw, rh, encoding) == (0, 0, 2, 2, 0)
        assert len(_recv_exact(client, rw * rh * 4)) == 16

        client.sendall(struct.pack(">BBHHHH", 150, 0, 0, 0, 2, 2))
        assert _recv_exact(client, 1) == b"\x96"
    finally:
        client.close()
        server.shutdown_handler.shutdown()
        thread.join(timeout=5.0)
        assert not thread.is_alive()


def test_real_server_extended_desktop_size_and_resize_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "ScreenCapture", _ResizingFakeCapture)
    monkeypatch.setattr(server_module, "InputHandler", _FakeInputHandler)

    port = _free_tcp_port()
    config = tmp_path / "server-extended-desktop.toml"
    config.write_text(
        f"""[server]
host = "127.0.0.1"
port = {port}
frame_rate = 30
lan_frame_rate = 30
network_profile_override = "auto"
max_connections = 2
max_connections_per_ip = 2
max_unauthenticated_connections = 2
handshake_timeout = 2.0
client_socket_timeout = 2.0

[features]
enable_metrics = false
enable_health_checks = false
enable_capture_producer = false
enable_parallel_encoding = false
enable_region_detection = false
enable_websocket = false
enable_tight_extensions = false
enable_tight_encoding = false
enable_jpeg_encoding = false
enable_zrle_encoding = false
enable_copyrect_encoding = false
enable_continuous_updates = false
enable_fence = false
enable_last_rect = false
enable_extended_desktop_size = true
allow_client_resize = false
""",
        encoding="utf-8",
    )

    server = server_module.VNCServerV3(config)
    thread = threading.Thread(target=server.start, name="test-vnc-extended-desktop")
    thread.start()

    client = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    client.settimeout(2.0)
    try:
        version = _recv_exact(client, 12)
        client.sendall(version)
        count = _recv_exact(client, 1)[0]
        security_types = _recv_exact(client, count)
        assert 1 in security_types
        client.sendall(b"\x01")
        assert _recv_exact(client, 4) == b"\x00\x00\x00\x00"
        client.sendall(b"\x01")

        width, height = struct.unpack(">HH", _recv_exact(client, 4))
        assert (width, height) == (2, 2)
        _recv_exact(client, 16)
        name_length = struct.unpack(">I", _recv_exact(client, 4))[0]
        _recv_exact(client, name_length)

        encodings = (0, -308)
        client.sendall(
            struct.pack(">BBH", 2, 0, len(encodings))
            + struct.pack(">" + "i" * len(encodings), *encodings)
        )

        # Negotiating -308 immediately advertises the current screen layout.
        msg_type, count = struct.unpack(">BxH", _recv_exact(client, 4))
        assert (msg_type, count) == (0, 1)
        reason, status, advertised_w, advertised_h, encoding = struct.unpack(
            ">HHHHi", _recv_exact(client, 12)
        )
        assert (reason, status, advertised_w, advertised_h, encoding) == (
            0, 0, 2, 2, -308
        )
        assert struct.unpack(">B3s", _recv_exact(client, 4))[0] == 1
        assert struct.unpack(">IHHHHI", _recv_exact(client, 16)) == (
            0, 0, 0, 2, 2, 0
        )

        client.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, 2, 2))

        msg_type, count = struct.unpack(">BxH", _recv_exact(client, 4))
        assert (msg_type, count) == (0, 1)
        reason, status, new_w, new_h, encoding = struct.unpack(
            ">HHHHi", _recv_exact(client, 12)
        )
        assert (reason, status, new_w, new_h, encoding) == (0, 0, 3, 2, -308)

        number_of_screens, padding = struct.unpack(">B3s", _recv_exact(client, 4))
        assert number_of_screens == 1
        assert padding == b"\x00\x00\x00"
        screen = struct.unpack(">IHHHHI", _recv_exact(client, 16))
        assert screen == (0, 0, 0, 3, 2, 0)

        # SetDesktopSize is parsed but host resize is safely rejected by default.
        requested_screen = struct.pack(">IHHHHI", 0, 0, 0, 3, 2, 0)
        client.sendall(
            struct.pack(">BBHHBB", 251, 0, 3, 2, 1, 0)
            + requested_screen
        )
        msg_type, count = struct.unpack(">BxH", _recv_exact(client, 4))
        assert (msg_type, count) == (0, 1)
        reason, status, rw, rh, encoding = struct.unpack(
            ">HHHHi", _recv_exact(client, 12)
        )
        assert (reason, status, rw, rh, encoding) == (1, 1, 3, 2, -308)
        _recv_exact(client, 4 + 16)
    finally:
        client.close()
        server.shutdown_handler.shutdown()
        thread.join(timeout=5.0)
        assert not thread.is_alive()


def test_real_server_vencrypt_x509_none_full_handshake(tmp_path, monkeypatch, tls_identity):
    """VeNCrypt X509None upgrades the real server socket before SecurityResult."""
    import ssl

    monkeypatch.setattr(server_module, "ScreenCapture", _FakeCapture)
    monkeypatch.setattr(server_module, "InputHandler", _FakeInputHandler)

    cert, key = tls_identity
    port = _free_tcp_port()
    config = tmp_path / "server-vencrypt.toml"
    config.write_text(
        f'''[server]\nhost = "127.0.0.1"\nport = {port}\nframe_rate = 30\nlan_frame_rate = 30\nnetwork_profile_override = "auto"\nmax_connections = 2\nmax_connections_per_ip = 2\nmax_unauthenticated_connections = 2\nhandshake_timeout = 3.0\nclient_socket_timeout = 3.0\n\n[security]\nvencrypt_enabled = true\nvencrypt_subtypes = ["x509-none"]\ntls_cert_file = "{cert.as_posix()}"\ntls_key_file = "{key.as_posix()}"\nrequire_encrypted_transport = true\n\n[features]\nenable_metrics = false\nenable_health_checks = false\nenable_capture_producer = false\nenable_parallel_encoding = false\nenable_region_detection = false\nenable_websocket = false\nenable_tight_extensions = false\nenable_tight_encoding = false\nenable_jpeg_encoding = false\nenable_zrle_encoding = false\nenable_copyrect_encoding = false\n''',
        encoding="utf-8",
    )

    server = server_module.VNCServerV3(config)
    thread = threading.Thread(target=server.start, name="test-vnc-vencrypt")
    thread.start()

    client = socket.create_connection(("127.0.0.1", port), timeout=3.0)
    client.settimeout(3.0)
    try:
        version = _recv_exact(client, 12)
        assert version == b"RFB 003.008\n"
        client.sendall(version)

        count = _recv_exact(client, 1)[0]
        security_types = _recv_exact(client, count)
        assert security_types == b"\x13"  # encryption is required
        client.sendall(b"\x13")

        assert _recv_exact(client, 2) == b"\x00\x02"
        client.sendall(b"\x00\x02")
        assert _recv_exact(client, 1) == b"\x00"
        subtype_count = _recv_exact(client, 1)[0]
        assert subtype_count == 1
        assert struct.unpack(">I", _recv_exact(client, 4))[0] == 260
        client.sendall(struct.pack(">I", 260))
        assert _recv_exact(client, 1) == b"\x01"

        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        client = tls_context.wrap_socket(client, server_hostname="localhost")
        client.settimeout(3.0)

        # SecurityResult is sent inside the encrypted channel.
        assert _recv_exact(client, 4) == b"\x00\x00\x00\x00"
        client.sendall(b"\x01")
        width, height = struct.unpack(">HH", _recv_exact(client, 4))
        assert (width, height) == (2, 2)
        _recv_exact(client, 16)
        name_length = struct.unpack(">I", _recv_exact(client, 4))[0]
        assert b"PyVNCServer" in _recv_exact(client, name_length)

        client.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, 2, 2))
        message_type, rectangle_count = struct.unpack(">BxH", _recv_exact(client, 4))
        assert message_type == 0
        assert rectangle_count >= 1
        x, y, rw, rh, encoding = struct.unpack(">HHHHi", _recv_exact(client, 12))
        assert (x, y, rw, rh, encoding) == (0, 0, 2, 2, 0)
        assert len(_recv_exact(client, rw * rh * 4)) == 16
    finally:
        try:
            client.close()
        except Exception:
            pass
        server.shutdown_handler.shutdown()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
