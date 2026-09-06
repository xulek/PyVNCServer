"""End-to-end loopback RFB smoke test for the real server session path."""

from __future__ import annotations

import socket
import struct
import threading

from pyvncserver.app import server as server_module
from vnc_lib.capture_backends import CaptureBackendCapabilities, CaptureFrame, CaptureMetadata
from vnc_lib.screen_capture import CaptureResult


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
