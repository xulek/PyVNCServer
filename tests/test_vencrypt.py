"""VeNCrypt 0.2 negotiation and TLS transport tests."""

from __future__ import annotations

from types import SimpleNamespace
import socket
import ssl
import struct
import threading

import pytest

from pyvncserver.config import ServerSettings
from vnc_lib.exceptions import ConfigurationError, ConnectionError, ProtocolError
from vnc_lib.protocol import RFBProtocol
from vnc_lib.vencrypt import (
    VeNCryptServer,
    VENCRYPT_SUBTYPE_TLS_NONE,
    VENCRYPT_SUBTYPE_TLS_VNC,
    VENCRYPT_SUBTYPE_X509_NONE,
    VENCRYPT_SUBTYPE_X509_VNC,
)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise RuntimeError("unexpected EOF")
        data.extend(chunk)
    return bytes(data)


def _client_x509_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _client_anonymous_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("aNULL:@SECLEVEL=0")
    return ctx


def _perform_client_vencrypt(sock: socket.socket, subtype: int, context: ssl.SSLContext):
    assert _recv_exact(sock, 2) == b"\x00\x02"
    sock.sendall(b"\x00\x02")
    assert _recv_exact(sock, 1) == b"\x00"
    count = _recv_exact(sock, 1)[0]
    offered = tuple(struct.unpack(">I", _recv_exact(sock, 4))[0] for _ in range(count))
    assert subtype in offered
    sock.sendall(struct.pack(">I", subtype))
    assert _recv_exact(sock, 1) == b"\x01"
    return context.wrap_socket(sock, server_hostname="localhost")


def test_x509_none_real_tls_round_trip(tls_identity):
    cert, key = tls_identity
    server_sock, client_sock = socket.socketpair()
    server = VeNCryptServer(
        cert_file=str(cert),
        key_file=str(key),
        subtype_names=("x509-none",),
    )
    outcome = {}

    def server_side():
        try:
            result = server.negotiate(server_sock, has_vnc_auth=False)
            outcome["subtype"] = result.subtype
            outcome["needs_auth"] = result.needs_auth
            outcome["tls_version"] = result.socket.version()
            outcome["data"] = result.socket.recv(4)
            result.socket.sendall(b"pong")
            result.socket.close()
        except BaseException as exc:  # surfaced in the main test thread
            outcome["error"] = exc

    thread = threading.Thread(target=server_side, daemon=True)
    thread.start()
    tls_client = _perform_client_vencrypt(
        client_sock, VENCRYPT_SUBTYPE_X509_NONE, _client_x509_context()
    )
    tls_client.sendall(b"ping")
    assert _recv_exact(tls_client, 4) == b"pong"
    tls_client.close()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert "error" not in outcome
    assert outcome["subtype"] == VENCRYPT_SUBTYPE_X509_NONE
    assert outcome["needs_auth"] is False
    assert outcome["tls_version"] in {"TLSv1.2", "TLSv1.3"}
    assert outcome["data"] == b"ping"


def test_x509_vnc_real_tls_round_trip_marks_auth_required(tls_identity):
    cert, key = tls_identity
    server_sock, client_sock = socket.socketpair()
    server = VeNCryptServer(
        cert_file=str(cert),
        key_file=str(key),
        subtype_names=("x509-vnc",),
    )
    outcome = {}

    def server_side():
        try:
            result = server.negotiate(server_sock, has_vnc_auth=True)
            outcome["subtype"] = result.subtype
            outcome["needs_auth"] = result.needs_auth
            result.socket.sendall(b"ready")
            result.socket.close()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=server_side, daemon=True)
    thread.start()
    tls_client = _perform_client_vencrypt(
        client_sock, VENCRYPT_SUBTYPE_X509_VNC, _client_x509_context()
    )
    assert _recv_exact(tls_client, 5) == b"ready"
    tls_client.close()
    thread.join(timeout=5)

    assert "error" not in outcome
    assert outcome == {
        "subtype": VENCRYPT_SUBTYPE_X509_VNC,
        "needs_auth": True,
    }


def test_anonymous_tls_none_round_trip_when_explicitly_enabled():
    server_sock, client_sock = socket.socketpair()
    server = VeNCryptServer(
        subtype_names=("tls-none",),
        allow_anonymous_tls=True,
    )
    outcome = {}

    def server_side():
        try:
            result = server.negotiate(server_sock, has_vnc_auth=False)
            outcome["needs_auth"] = result.needs_auth
            outcome["version"] = result.socket.version()
            result.socket.sendall(b"ok")
            result.socket.close()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=server_side, daemon=True)
    thread.start()
    tls_client = _perform_client_vencrypt(
        client_sock, VENCRYPT_SUBTYPE_TLS_NONE, _client_anonymous_context()
    )
    assert _recv_exact(tls_client, 2) == b"ok"
    tls_client.close()
    thread.join(timeout=5)

    assert "error" not in outcome
    assert outcome["needs_auth"] is False
    assert outcome["version"] == "TLSv1.2"


def test_no_auth_subtype_cannot_bypass_configured_vnc_password(tls_identity):
    cert, key = tls_identity
    server = VeNCryptServer(
        cert_file=str(cert),
        key_file=str(key),
        subtype_names=("x509-none", "x509-vnc"),
    )
    assert server.available_subtypes(has_vnc_auth=True) == (
        VENCRYPT_SUBTYPE_X509_VNC,
    )


def test_explicit_no_auth_bypass_requires_explicit_opt_in(tls_identity):
    cert, key = tls_identity
    server = VeNCryptServer(
        cert_file=str(cert),
        key_file=str(key),
        subtype_names=("x509-none", "x509-vnc"),
        allow_no_auth_with_password=True,
    )
    assert server.available_subtypes(has_vnc_auth=True) == (
        VENCRYPT_SUBTYPE_X509_NONE,
        VENCRYPT_SUBTYPE_X509_VNC,
    )


def test_anonymous_subtypes_are_not_offered_by_default():
    server = VeNCryptServer(subtype_names=("tls-none", "tls-vnc"))
    assert server.available_subtypes(False) == ()
    assert server.available_subtypes(True) == ()


def test_vencrypt_rejects_wrong_version(tls_identity):
    cert, key = tls_identity
    class FakeSocket:
        def __init__(self):
            self.recv_data = bytearray(b"\x00\x01")
            self.sent = bytearray()

        def sendall(self, data):
            self.sent.extend(data)

        def recv(self, n):
            out = bytes(self.recv_data[:n])
            del self.recv_data[:n]
            return out

    sock = FakeSocket()
    server = VeNCryptServer(
        cert_file=str(cert), key_file=str(key), subtype_names=("x509-none",)
    )
    with pytest.raises(ProtocolError, match="0.1"):
        server.negotiate(sock, has_vnc_auth=False)
    assert bytes(sock.sent) == b"\x00\x02\x01"


def test_protocol_offers_vencrypt_first_and_uses_upgraded_socket():
    class FakeSocket:
        def __init__(self):
            self.recv_data = bytearray(b"\x13")
            self.sent = bytearray()

        def sendall(self, data):
            self.sent.extend(data)

        def recv(self, n):
            out = bytes(self.recv_data[:n])
            del self.recv_data[:n]
            return out

    upgraded = object()

    class FakeVeNCrypt:
        def available_subtypes(self, has_vnc_auth):
            assert has_vnc_auth is True
            return (VENCRYPT_SUBTYPE_X509_VNC,)

        def negotiate(self, sock, *, has_vnc_auth):
            assert has_vnc_auth is True
            return SimpleNamespace(
                socket=upgraded,
                subtype=VENCRYPT_SUBTYPE_X509_VNC,
                needs_auth=True,
            )

    protocol = RFBProtocol()
    protocol.version = (3, 8)
    sock = FakeSocket()
    result = protocol.negotiate_security(
        sock,
        "secret",
        allow_tight_security=True,
        vencrypt_server=FakeVeNCrypt(),
    )

    assert bytes(sock.sent[:4]) == bytes((3, 19, 2, 16))
    assert result.security_type == 19
    assert result.auth_type == 2
    assert result.needs_auth is True
    assert result.encrypted is True
    assert result.transport_socket is upgraded


def test_require_encryption_offers_only_vencrypt():
    class FakeSocket:
        def __init__(self):
            self.recv_data = bytearray(b"\x13")
            self.sent = bytearray()

        def sendall(self, data):
            self.sent.extend(data)

        def recv(self, n):
            out = bytes(self.recv_data[:n])
            del self.recv_data[:n]
            return out

    class FakeVeNCrypt:
        def available_subtypes(self, _has_vnc_auth):
            return (VENCRYPT_SUBTYPE_X509_VNC,)

        def negotiate(self, sock, *, has_vnc_auth):
            return SimpleNamespace(
                socket=sock,
                subtype=VENCRYPT_SUBTYPE_X509_VNC,
                needs_auth=has_vnc_auth,
            )

    protocol = RFBProtocol()
    protocol.version = (3, 8)
    sock = FakeSocket()
    protocol.negotiate_security(
        sock,
        "secret",
        vencrypt_server=FakeVeNCrypt(),
        require_encrypted_transport=True,
    )
    assert bytes(sock.sent[:2]) == b"\x01\x13"


def test_rfb33_cannot_satisfy_require_encrypted_transport():
    protocol = RFBProtocol()
    protocol.version = (3, 3)

    class FakeSocket:
        def sendall(self, _data):
            raise AssertionError("must fail before advertising insecure RFB 3.3 auth")

    with pytest.raises(ConnectionError, match="RFB 3.3"):
        protocol.negotiate_security(
            FakeSocket(),
            "secret",
            require_encrypted_transport=True,
        )


def test_config_rejects_direct_tls_and_vencrypt_together(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("x")
    key.write_text("x")
    with pytest.raises(ConfigurationError, match="cannot be enabled"):
        ServerSettings.from_mapping({
            "tls_enabled": True,
            "vencrypt_enabled": True,
            "tls_cert_file": str(cert),
            "tls_key_file": str(key),
        })


def test_config_vencrypt_x509_requires_identity():
    with pytest.raises(ConfigurationError, match="require tls_cert_file"):
        ServerSettings.from_mapping({"vencrypt_enabled": True})


def test_config_anonymous_tls_requires_explicit_opt_in():
    with pytest.raises(ConfigurationError, match="allow_anonymous_tls"):
        ServerSettings.from_mapping({
            "vencrypt_enabled": True,
            "vencrypt_subtypes": ["tls-vnc"],
        })


def test_config_requires_encryption_backend():
    with pytest.raises(ConfigurationError, match="require_encrypted_transport"):
        ServerSettings.from_mapping({"require_encrypted_transport": True})


def test_anonymous_tls_vnc_marks_auth_required():
    server_sock, client_sock = socket.socketpair()
    server = VeNCryptServer(
        subtype_names=("tls-vnc",),
        allow_anonymous_tls=True,
    )
    outcome = {}

    def server_side():
        try:
            result = server.negotiate(server_sock, has_vnc_auth=True)
            outcome["subtype"] = result.subtype
            outcome["needs_auth"] = result.needs_auth
            result.socket.sendall(b"auth")
            result.socket.close()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=server_side, daemon=True)
    thread.start()
    tls_client = _perform_client_vencrypt(
        client_sock, VENCRYPT_SUBTYPE_TLS_VNC, _client_anonymous_context()
    )
    assert _recv_exact(tls_client, 4) == b"auth"
    tls_client.close()
    thread.join(timeout=5)

    assert "error" not in outcome
    assert outcome == {
        "subtype": VENCRYPT_SUBTYPE_TLS_VNC,
        "needs_auth": True,
    }


def test_validate_configuration_fails_fast_on_invalid_x509_identity(tmp_path):
    cert = tmp_path / "broken-cert.pem"
    key = tmp_path / "broken-key.pem"
    cert.write_text("not a certificate", encoding="utf-8")
    key.write_text("not a private key", encoding="utf-8")
    server = VeNCryptServer(
        cert_file=str(cert),
        key_file=str(key),
        subtype_names=("x509-none",),
    )
    with pytest.raises(ssl.SSLError):
        server.validate_configuration(has_vnc_auth=False)


def test_minimum_tls_13_is_applied_to_x509_context(tls_identity):
    cert, key = tls_identity
    server = VeNCryptServer(
        cert_file=str(cert),
        key_file=str(key),
        subtype_names=("x509-none",),
        minimum_tls_version="1.3",
    )
    server.validate_configuration(has_vnc_auth=False)
    assert server._get_x509_context().minimum_version == ssl.TLSVersion.TLSv1_3


def test_config_rejects_vnc_subtype_without_vnc_password(tls_identity):
    cert, key = tls_identity
    with pytest.raises(ConfigurationError, match="no subtype usable"):
        ServerSettings.from_mapping({
            "vencrypt_enabled": True,
            "vencrypt_subtypes": ["x509-vnc"],
            "tls_cert_file": str(cert),
            "tls_key_file": str(key),
        })


def test_config_rejects_none_only_subtype_as_password_bypass(tls_identity):
    cert, key = tls_identity
    with pytest.raises(ConfigurationError, match="no subtype usable"):
        ServerSettings.from_mapping({
            "password": "secret",
            "vencrypt_enabled": True,
            "vencrypt_subtypes": ["x509-none"],
            "tls_cert_file": str(cert),
            "tls_key_file": str(key),
        })
