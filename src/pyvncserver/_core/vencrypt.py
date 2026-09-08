"""VeNCrypt 0.2 transport upgrade support for RFB security type 19."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import ssl
import struct
from typing import Iterable

from .exceptions import ConnectionError, ProtocolError
from .io_utils import recv_exact


VENCRYPT_VERSION = (0, 2)
VENCRYPT_SUBTYPE_PLAIN = 256
VENCRYPT_SUBTYPE_TLS_NONE = 257
VENCRYPT_SUBTYPE_TLS_VNC = 258
VENCRYPT_SUBTYPE_X509_NONE = 260
VENCRYPT_SUBTYPE_X509_VNC = 261

SUBTYPE_NAMES = {
    VENCRYPT_SUBTYPE_TLS_NONE: "TLSNone",
    VENCRYPT_SUBTYPE_TLS_VNC: "TLSVnc",
    VENCRYPT_SUBTYPE_X509_NONE: "X509None",
    VENCRYPT_SUBTYPE_X509_VNC: "X509Vnc",
}

NAME_TO_SUBTYPE = {
    "tls-none": VENCRYPT_SUBTYPE_TLS_NONE,
    "tlsnone": VENCRYPT_SUBTYPE_TLS_NONE,
    "tls-vnc": VENCRYPT_SUBTYPE_TLS_VNC,
    "tlsvnc": VENCRYPT_SUBTYPE_TLS_VNC,
    "x509-none": VENCRYPT_SUBTYPE_X509_NONE,
    "x509none": VENCRYPT_SUBTYPE_X509_NONE,
    "x509-vnc": VENCRYPT_SUBTYPE_X509_VNC,
    "x509vnc": VENCRYPT_SUBTYPE_X509_VNC,
}

TLS_SUBTYPES = frozenset({VENCRYPT_SUBTYPE_TLS_NONE, VENCRYPT_SUBTYPE_TLS_VNC})
X509_SUBTYPES = frozenset({VENCRYPT_SUBTYPE_X509_NONE, VENCRYPT_SUBTYPE_X509_VNC})
VNC_AUTH_SUBTYPES = frozenset({VENCRYPT_SUBTYPE_TLS_VNC, VENCRYPT_SUBTYPE_X509_VNC})
NO_AUTH_SUBTYPES = frozenset({VENCRYPT_SUBTYPE_TLS_NONE, VENCRYPT_SUBTYPE_X509_NONE})


@dataclass(slots=True, frozen=True)
class VeNCryptResult:
    """Result of a successful VeNCrypt 0.2 negotiation."""

    socket: object
    subtype: int
    needs_auth: bool


class VeNCryptServer:
    """Negotiate VeNCrypt 0.2 and upgrade a raw RFB socket to TLS.

    X509 subtypes use the configured server certificate. Historical TLSNone and
    TLSVnc use anonymous TLS cipher suites and are disabled unless explicitly
    requested by configuration because anonymous TLS is not suitable as a
    modern authenticity mechanism.
    """

    def __init__(
        self,
        *,
        cert_file: str = "",
        key_file: str = "",
        subtype_names: Iterable[str] = (),
        allow_anonymous_tls: bool = False,
        allow_no_auth_with_password: bool = False,
        minimum_tls_version: str = "1.2",
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.cert_file = str(cert_file or "")
        self.key_file = str(key_file or "")
        self.allow_anonymous_tls = bool(allow_anonymous_tls)
        self.allow_no_auth_with_password = bool(allow_no_auth_with_password)
        self.minimum_tls_version = str(minimum_tls_version or "1.2")

        parsed: list[int] = []
        for name in subtype_names:
            normalized = str(name).strip().lower().replace("_", "-")
            if not normalized:
                continue
            subtype = NAME_TO_SUBTYPE.get(normalized)
            if subtype is None:
                raise ValueError(f"Unsupported VeNCrypt subtype: {name}")
            if subtype not in parsed:
                parsed.append(subtype)
        self.configured_subtypes = tuple(parsed)

        self._x509_context: ssl.SSLContext | None = None
        self._anonymous_context: ssl.SSLContext | None = None

    @property
    def has_x509_identity(self) -> bool:
        return bool(self.cert_file and self.key_file)

    def validate_configuration(self, *, has_vnc_auth: bool) -> tuple[int, ...]:
        """Fail fast if the configured VeNCrypt policy cannot be served."""
        subtypes = self.available_subtypes(has_vnc_auth)
        if not subtypes:
            raise ValueError("VeNCrypt has no usable subtypes for the current authentication policy")
        if any(subtype in X509_SUBTYPES for subtype in subtypes):
            self._get_x509_context()
        if any(subtype in TLS_SUBTYPES for subtype in subtypes):
            self._get_anonymous_context()
        return subtypes

    def available_subtypes(self, has_vnc_auth: bool) -> tuple[int, ...]:
        """Return safe, usable subtypes in server preference order."""
        if self.configured_subtypes:
            candidates = self.configured_subtypes
        elif has_vnc_auth:
            candidates = (VENCRYPT_SUBTYPE_X509_VNC,)
        else:
            candidates = (VENCRYPT_SUBTYPE_X509_NONE,)

        available: list[int] = []
        for subtype in candidates:
            if subtype in X509_SUBTYPES and not self.has_x509_identity:
                continue
            if subtype in TLS_SUBTYPES and not self.allow_anonymous_tls:
                continue
            if subtype in VNC_AUTH_SUBTYPES and not has_vnc_auth:
                continue
            if (
                subtype in NO_AUTH_SUBTYPES
                and has_vnc_auth
                and not self.allow_no_auth_with_password
            ):
                # Never silently create a password bypass just because a
                # no-auth encryption subtype appeared in a configured list.
                continue
            available.append(subtype)
        return tuple(available)

    def negotiate(self, client_socket, *, has_vnc_auth: bool) -> VeNCryptResult:
        """Perform the VeNCrypt 0.2 sub-handshake and TLS upgrade."""
        subtypes = self.available_subtypes(has_vnc_auth)
        if not subtypes:
            raise ConnectionError("VeNCrypt is enabled but no usable subtypes are configured")

        # Server advertises the highest VeNCrypt version it supports.
        client_socket.sendall(bytes(VENCRYPT_VERSION))
        client_version = recv_exact(client_socket, 2)
        if not client_version:
            raise ConnectionError("Client disconnected during VeNCrypt version negotiation")
        major, minor = client_version[0], client_version[1]
        if (major, minor) != VENCRYPT_VERSION:
            client_socket.sendall(b"\x01")
            raise ProtocolError(
                f"Unsupported VeNCrypt version {major}.{minor}; only 0.2 is supported"
            )

        # Version accepted: 0 means success at this stage.
        client_socket.sendall(b"\x00")
        client_socket.sendall(struct.pack("B", len(subtypes)))
        for subtype in subtypes:
            client_socket.sendall(struct.pack(">I", subtype))

        selection = recv_exact(client_socket, 4)
        if not selection:
            raise ConnectionError("Client disconnected during VeNCrypt subtype selection")
        subtype = struct.unpack(">I", selection)[0]
        if subtype not in subtypes:
            raise ProtocolError(f"Client selected unsupported VeNCrypt subtype: {subtype}")

        # VeNCrypt 0.2 acknowledges TLS/X509 subtypes with 1 before the TLS
        # handshake starts.
        client_socket.sendall(b"\x01")
        wrapped = self._wrap_socket(client_socket, subtype)
        self.logger.info(
            "VeNCrypt 0.2 negotiated subtype %s (%d)",
            SUBTYPE_NAMES.get(subtype, "unknown"),
            subtype,
        )
        return VeNCryptResult(
            socket=wrapped,
            subtype=subtype,
            needs_auth=subtype in VNC_AUTH_SUBTYPES,
        )

    def _wrap_socket(self, client_socket, subtype: int):
        if subtype in X509_SUBTYPES:
            context = self._get_x509_context()
        elif subtype in TLS_SUBTYPES:
            context = self._get_anonymous_context()
        else:
            raise ProtocolError(f"Unsupported TLS VeNCrypt subtype: {subtype}")

        try:
            return context.wrap_socket(client_socket, server_side=True)
        except (ssl.SSLError, OSError) as exc:
            raise ConnectionError(f"VeNCrypt TLS handshake failed: {exc}") from exc

    def _get_x509_context(self) -> ssl.SSLContext:
        if self._x509_context is None:
            if not self.has_x509_identity:
                raise ConnectionError("X509 VeNCrypt subtype requires certificate and key")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = parse_minimum_tls_version(self.minimum_tls_version)
            context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
            context.load_cert_chain(self.cert_file, self.key_file)
            self._x509_context = context
        return self._x509_context

    def _get_anonymous_context(self) -> ssl.SSLContext:
        if not self.allow_anonymous_tls:
            raise ConnectionError("Anonymous VeNCrypt TLS subtypes are disabled")
        if self._anonymous_context is None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            # Anonymous cipher suites do not exist in TLS 1.3. Keep this
            # compatibility mode isolated at TLS 1.2 and never weaken X509.
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.maximum_version = ssl.TLSVersion.TLSv1_2
            context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
            try:
                context.set_ciphers("aNULL:@SECLEVEL=0")
            except ssl.SSLError as exc:
                raise ConnectionError(
                    "This OpenSSL build does not support anonymous TLS cipher suites"
                ) from exc
            self._anonymous_context = context
        return self._anonymous_context


def parse_minimum_tls_version(value: str) -> ssl.TLSVersion:
    normalized = str(value).strip().lower().replace("tls", "").replace("v", "")
    normalized = normalized.strip(" .")
    if normalized in {"1.2", "12"}:
        return ssl.TLSVersion.TLSv1_2
    if normalized in {"1.3", "13"}:
        return ssl.TLSVersion.TLSv1_3
    raise ValueError("minimum TLS version must be 1.2 or 1.3")
