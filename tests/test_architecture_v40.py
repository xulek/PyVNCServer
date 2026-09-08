"""Architecture and plugin integration tests for the 4.0 major release."""

from __future__ import annotations

import socket
import struct
import threading
from pathlib import Path

import pytest

from pyvncserver import PluginManager
from pyvncserver.capture import CaptureMetadata, ScreenCapture
from pyvncserver.encodings import EncoderManager
from pyvncserver.plugins import SecurityPluginResult
from pyvncserver.protocol import RFBProtocol


class _PluginCaptureBackend:
    name = "memory"

    def __init__(self, _owner):
        self.frames = 0

    def is_available(self) -> bool:
        return True

    def healthcheck(self) -> bool:
        return True

    def grab_bgra(self):
        self.frames += 1
        return b"\x00\x00\x00\x00", 1, 1

    def grab_rgb(self):
        self.frames += 1
        return b"\x00\x00\x00", 1, 1

    def build_metadata(self, _width: int, _height: int):
        return CaptureMetadata(backend_name=self.name)


class _CapturePlugin:
    name = "memory"

    def create_backend(self, owner):
        return _PluginCaptureBackend(owner)


class _MarkerEncoder:
    def encode(self, _pixel_data: bytes, width: int, height: int, _bpp: int) -> bytes:
        return b"plugin:" + bytes((width & 0xFF, height & 0xFF))


class _EncodingPlugin:
    encoding_id = 123
    name = "marker"

    def create_encoder(self):
        return _MarkerEncoder()


class _SecurityPlugin:
    security_type = 42
    name = "test-secure"
    encrypted = True

    def is_available(self, _has_vnc_auth: bool) -> bool:
        return True

    def negotiate(self, client_socket, _has_vnc_auth: bool) -> SecurityPluginResult:
        marker = client_socket.recv(1)
        assert marker == b"P"
        return SecurityPluginResult(auth_type=1, encrypted=True)


def test_top_level_legacy_package_is_removed():
    project_root = Path(__file__).resolve().parents[1]
    assert not (project_root / "src" / "vnc_lib").exists()

    offenders = []
    for path in (project_root / "src" / "pyvncserver").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from vnc_lib" in text or "import vnc_lib" in text:
            offenders.append(path.relative_to(project_root).as_posix())
    assert offenders == []


def test_public_facades_are_importable_without_private_modules():
    from pyvncserver.capture import CaptureFrame, CaptureMoveRect
    from pyvncserver.encodings import RawEncoder, TightEncoder
    from pyvncserver.errors import ConfigurationError
    from pyvncserver.protocol import SecurityTypes
    from pyvncserver.security import VNCAuth, VeNCryptServer

    assert CaptureFrame is not None
    assert CaptureMoveRect is not None
    assert RawEncoder is not None
    assert TightEncoder is not None
    assert ConfigurationError is not None
    assert SecurityTypes is not None
    assert VNCAuth is not None
    assert VeNCryptServer is not None


def test_capture_plugin_is_selected_by_screen_capture():
    manager = PluginManager().extend(capture=[_CapturePlugin()])
    capture = ScreenCapture(
        backend_preference="memory",
        backend_factories=manager.capture_factories(),
    )
    assert capture.get_backend_name() == "memory"
    assert capture.get_backend_capabilities().backend_name == "memory"


def test_encoding_plugin_is_available_to_encoder_manager():
    manager = PluginManager().extend(encodings=[_EncodingPlugin()])
    encoders = EncoderManager(extra_encoders=manager.create_encoders())
    encoding_id, encoder = encoders.get_best_encoder([123, 0])
    assert encoding_id == 123
    assert encoder.encode(b"", 2, 3, 4) == b"plugin:\x02\x03"


def test_plugin_manager_rejects_reserved_ids_and_names():
    manager = PluginManager()

    class BadCapture(_CapturePlugin):
        name = "mss"

    class BadEncoding(_EncodingPlugin):
        encoding_id = 7

    class BadSecurity(_SecurityPlugin):
        security_type = 19

    with pytest.raises(ValueError):
        manager.register_capture(BadCapture())
    with pytest.raises(ValueError):
        manager.register_encoding(BadEncoding())
    with pytest.raises(ValueError):
        manager.register_security(BadSecurity())


def test_security_plugin_participates_in_rfb_38_negotiation():
    manager = PluginManager().extend(security=[_SecurityPlugin()])
    server_sock, client_sock = socket.socketpair()
    result_box = {}
    error_box = {}

    def run_server():
        try:
            protocol = RFBProtocol()
            protocol.version = (3, 8)
            result_box["value"] = protocol.negotiate_security(
                server_sock,
                None,
                allow_tight_security=False,
                require_encrypted_transport=True,
                extra_security_plugins=manager.security_plugins(),
            )
        except BaseException as exc:  # surfaced in the assertion below
            error_box["value"] = exc

    thread = threading.Thread(target=run_server)
    thread.start()
    try:
        count = client_sock.recv(1)[0]
        advertised = tuple(client_sock.recv(count))
        assert advertised == (42,)
        client_sock.sendall(struct.pack("B", 42) + b"P")
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert "value" not in error_box
        result = result_box["value"]
        assert result.security_type == 42
        assert result.encrypted is True
        assert result.needs_auth is False
    finally:
        server_sock.close()
        client_sock.close()

class _PlainSecurityPlugin(_SecurityPlugin):
    security_type = 43
    name = "test-plain"
    encrypted = False


def test_encryption_policy_filters_unencrypted_security_plugins():
    manager = PluginManager().extend(security=[_PlainSecurityPlugin(), _SecurityPlugin()])
    server_sock, client_sock = socket.socketpair()
    errors = []

    def run_server():
        try:
            protocol = RFBProtocol()
            protocol.version = (3, 8)
            protocol.negotiate_security(
                server_sock,
                None,
                allow_tight_security=False,
                require_encrypted_transport=True,
                extra_security_plugins=manager.security_plugins(),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_server)
    thread.start()
    try:
        count = client_sock.recv(1)[0]
        advertised = tuple(client_sock.recv(count))
        assert advertised == (42,)
        client_sock.close()
        thread.join(timeout=2)
    finally:
        server_sock.close()
        try:
            client_sock.close()
        except OSError:
            pass


def test_plugin_managers_are_isolated():
    left = PluginManager().extend(encodings=[_EncodingPlugin()])
    right = PluginManager()
    assert left.encoding_ids == (123,)
    assert right.encoding_ids == ()

class _LyingSecurityPlugin(_SecurityPlugin):
    security_type = 44
    name = "lying-secure"
    encrypted = True

    def negotiate(self, client_socket, _has_vnc_auth: bool) -> SecurityPluginResult:
        assert client_socket.recv(1) == b"P"
        return SecurityPluginResult(auth_type=1, encrypted=False)


def test_security_plugin_cannot_bypass_encrypted_transport_policy():
    manager = PluginManager().extend(security=[_LyingSecurityPlugin()])
    server_sock, client_sock = socket.socketpair()
    errors = []

    def run_server():
        try:
            protocol = RFBProtocol()
            protocol.version = (3, 8)
            protocol.negotiate_security(
                server_sock,
                None,
                allow_tight_security=False,
                require_encrypted_transport=True,
                extra_security_plugins=manager.security_plugins(),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_server)
    thread.start()
    try:
        count = client_sock.recv(1)[0]
        assert tuple(client_sock.recv(count)) == (44,)
        client_sock.sendall(b",P")  # 44 + plugin marker
        failure = client_sock.recv(4)
        thread.join(timeout=2)
        assert failure == b"\x00\x00\x00\x01"
        assert errors
    finally:
        server_sock.close()
        client_sock.close()


def test_encoding_factories_create_client_local_instances():
    manager = PluginManager().extend(encodings=[_EncodingPlugin()])
    left = manager.create_encoders()[123]
    right = manager.create_encoders()[123]
    assert left is not right
