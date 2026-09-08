"""Stable plugin contracts for PyVNCServer 4.x.

The contracts intentionally depend only on Python protocols and small dataclasses,
not on private implementation classes. Third-party plugins therefore do not need
to import :mod:`pyvncserver._core`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CaptureBackendProtocol(Protocol):
    """Runtime contract implemented by capture backend instances."""

    name: str

    def is_available(self) -> bool: ...
    def healthcheck(self) -> bool: ...
    def grab_bgra(self) -> tuple[bytes | None, int, int]: ...
    def grab_rgb(self) -> tuple[bytes | None, int, int]: ...
    def build_metadata(self, width: int, height: int) -> Any: ...


@runtime_checkable
class CaptureBackendPlugin(Protocol):
    """Factory contract for an additional screen-capture backend."""

    name: str

    def create_backend(self, owner: object) -> CaptureBackendProtocol: ...


@runtime_checkable
class EncoderProtocol(Protocol):
    """Minimal rectangle encoder contract."""

    def encode(self, pixel_data: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes: ...


@runtime_checkable
class EncodingPlugin(Protocol):
    """Factory contract for an additional RFB rectangle encoding."""

    encoding_id: int
    name: str

    def create_encoder(self) -> EncoderProtocol: ...


@dataclass(frozen=True, slots=True)
class SecurityPluginResult:
    """Normalized result returned by a custom RFB security plugin."""

    auth_type: int
    needs_auth: bool = False
    transport_socket: Any | None = None
    encrypted: bool = False
    send_security_result_on_success: bool = True
    send_security_result_on_failure: bool = True


@runtime_checkable
class SecurityPlugin(Protocol):
    """Contract for an additional RFB security type (RFB 3.7+)."""

    security_type: int
    name: str
    encrypted: bool

    def is_available(self, has_vnc_auth: bool) -> bool: ...
    def negotiate(self, client_socket: Any, has_vnc_auth: bool) -> SecurityPluginResult: ...
