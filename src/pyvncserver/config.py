"""Typed configuration loading and validation for PyVNCServer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import ipaddress
import tomllib

from vnc_lib.exceptions import ConfigurationError


DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.toml")


@dataclass(frozen=True, slots=True)
class SecuritySettings:
    """Security-sensitive server settings."""

    password: str = ""
    read_only_password: str = ""
    allow_insecure_no_auth: bool = False
    tls_enabled: bool = False
    tls_cert_file: str = ""
    tls_key_file: str = ""
    tls_minimum_version: str = "1.2"
    vencrypt_enabled: bool = False
    vencrypt_subtypes: tuple[str, ...] = ()
    vencrypt_allow_anonymous_tls: bool = False
    vencrypt_allow_no_auth_with_password: bool = False
    require_encrypted_transport: bool = False
    auth_max_failures: int = 5
    auth_failure_window_seconds: float = 30.0
    auth_backoff_max_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class WebSocketSettings:
    """WebSocket transport limits."""

    allowed_origins: tuple[str, ...] = ()
    detect_timeout: float = 0.5
    max_handshake_bytes: int = 64 * 1024
    max_payload_bytes: int = 8 * 1024 * 1024
    max_buffer_bytes: int = 16 * 1024 * 1024
    max_message_bytes: int = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """Typed core settings plus a compatibility mapping for tuning options."""

    host: str = "127.0.0.1"
    port: int = 5900
    frame_rate: int = 30
    lan_frame_rate: int = 90
    network_profile_override: str | None = None
    scale_factor: float = 1.0
    capture_backend: str = "auto"
    monitor_index: int = 0
    capture_all_monitors: bool = False
    max_connections: int = 10
    max_connections_per_ip: int = 4
    max_unauthenticated_connections: int = 4
    handshake_timeout: float = 5.0
    client_socket_timeout: float = 60.0
    input_control_policy: str = "single-controller"
    security: SecuritySettings = field(default_factory=SecuritySettings)
    websocket: WebSocketSettings = field(default_factory=WebSocketSettings)
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "ServerSettings":
        return cls.from_mapping(load_config_file(path or DEFAULT_CONFIG_PATH))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ServerSettings":
        data = dict(values)
        network_override = str(data.get("network_profile_override") or "").strip().lower()
        if network_override in {"", "auto", "none"}:
            network_override = None

        origins = data.get("websocket_allowed_origins", ())
        if isinstance(origins, str):
            origins = (origins,)
        else:
            origins = tuple(str(item) for item in origins or ())

        vencrypt_subtypes_raw = data.get("vencrypt_subtypes", ())
        if isinstance(vencrypt_subtypes_raw, str):
            vencrypt_subtypes = (vencrypt_subtypes_raw,)
        else:
            vencrypt_subtypes = tuple(str(item) for item in vencrypt_subtypes_raw or ())

        security = SecuritySettings(
            password=str(data.get("password", "")),
            read_only_password=str(data.get("read_only_password", "")),
            allow_insecure_no_auth=bool(data.get("allow_insecure_no_auth", False)),
            tls_enabled=bool(data.get("tls_enabled", False)),
            tls_cert_file=str(data.get("tls_cert_file", "")).strip(),
            tls_key_file=str(data.get("tls_key_file", "")).strip(),
            tls_minimum_version=str(data.get("tls_minimum_version", "1.2")).strip(),
            vencrypt_enabled=bool(data.get("vencrypt_enabled", False)),
            vencrypt_subtypes=tuple(item.strip() for item in vencrypt_subtypes if item.strip()),
            vencrypt_allow_anonymous_tls=bool(data.get("vencrypt_allow_anonymous_tls", False)),
            vencrypt_allow_no_auth_with_password=bool(data.get("vencrypt_allow_no_auth_with_password", False)),
            require_encrypted_transport=bool(data.get("require_encrypted_transport", False)),
            auth_max_failures=int(data.get("auth_max_failures", 5)),
            auth_failure_window_seconds=float(data.get("auth_failure_window_seconds", 30.0)),
            auth_backoff_max_seconds=float(data.get("auth_backoff_max_seconds", 2.0)),
        )
        websocket = WebSocketSettings(
            allowed_origins=tuple(origin.strip() for origin in origins if origin.strip()),
            detect_timeout=float(data.get("websocket_detect_timeout", 0.5)),
            max_handshake_bytes=int(data.get("websocket_max_handshake_bytes", 64 * 1024)),
            max_payload_bytes=int(data.get("websocket_max_payload_bytes", 8 * 1024 * 1024)),
            max_buffer_bytes=int(data.get("websocket_max_buffer_bytes", 16 * 1024 * 1024)),
            max_message_bytes=int(data.get("websocket_max_message_bytes", 16 * 1024 * 1024)),
        )

        known = {
            "host", "port", "frame_rate", "lan_frame_rate", "network_profile_override",
            "scale_factor", "capture_backend", "monitor_index", "capture_all_monitors",
            "max_connections",
            "max_connections_per_ip", "max_unauthenticated_connections",
            "handshake_timeout", "client_socket_timeout",
            "input_control_policy", "password", "read_only_password", "allow_insecure_no_auth",
            "tls_enabled", "tls_cert_file", "tls_key_file", "tls_minimum_version",
            "vencrypt_enabled", "vencrypt_subtypes", "vencrypt_allow_anonymous_tls",
            "vencrypt_allow_no_auth_with_password", "require_encrypted_transport",
            "auth_max_failures", "auth_failure_window_seconds", "auth_backoff_max_seconds",
            "websocket_allowed_origins", "websocket_detect_timeout",
            "websocket_max_handshake_bytes", "websocket_max_payload_bytes",
            "websocket_max_buffer_bytes", "websocket_max_message_bytes",
        }
        extra = {key: value for key, value in data.items() if key not in known}

        settings = cls(
            host=str(data.get("host", "127.0.0.1")).strip(),
            port=int(data.get("port", 5900)),
            frame_rate=int(data.get("frame_rate", 30)),
            lan_frame_rate=int(data.get("lan_frame_rate", 90)),
            network_profile_override=network_override,
            scale_factor=float(data.get("scale_factor", 1.0)),
            capture_backend=str(data.get("capture_backend", "auto")).strip().lower() or "auto",
            monitor_index=int(data.get("monitor_index", 0)),
            capture_all_monitors=bool(data.get("capture_all_monitors", False)),
            max_connections=int(data.get("max_connections", 10)),
            max_connections_per_ip=int(data.get("max_connections_per_ip", 4)),
            max_unauthenticated_connections=int(data.get("max_unauthenticated_connections", 4)),
            handshake_timeout=float(data.get("handshake_timeout", 5.0)),
            client_socket_timeout=float(data.get("client_socket_timeout", 60.0)),
            input_control_policy=str(data.get("input_control_policy", "single-controller")).strip().lower(),
            security=security,
            websocket=websocket,
            extra=extra,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.host:
            raise ConfigurationError("server.host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("server.port must be between 1 and 65535")
        if not 1 <= self.frame_rate <= 240:
            raise ConfigurationError("server.frame_rate must be between 1 and 240")
        if not 1 <= self.lan_frame_rate <= 240:
            raise ConfigurationError("server.lan_frame_rate must be between 1 and 240")
        if self.scale_factor <= 0:
            raise ConfigurationError("server.scale_factor must be greater than 0")
        if self.monitor_index < 0:
            raise ConfigurationError("server.monitor_index must not be negative")
        if self.max_connections < 1:
            raise ConfigurationError("server.max_connections must be at least 1")
        if not 1 <= self.max_connections_per_ip <= self.max_connections:
            raise ConfigurationError(
                "server.max_connections_per_ip must be between 1 and max_connections"
            )
        if not 1 <= self.max_unauthenticated_connections <= self.max_connections:
            raise ConfigurationError(
                "server.max_unauthenticated_connections must be between 1 and max_connections"
            )
        if self.handshake_timeout <= 0 or self.client_socket_timeout <= 0:
            raise ConfigurationError("socket timeouts must be greater than 0")
        if self.input_control_policy not in {"single-controller", "shared"}:
            raise ConfigurationError(
                "server.input_control_policy must be 'single-controller' or 'shared'"
            )
        if self.network_profile_override not in {None, "localhost", "lan", "wan"}:
            raise ConfigurationError(
                "server.network_profile_override must be auto, localhost, lan, or wan"
            )
        if self.security.auth_max_failures < 1:
            raise ConfigurationError("security.auth_max_failures must be at least 1")
        if self.security.auth_failure_window_seconds <= 0:
            raise ConfigurationError("security.auth_failure_window_seconds must be greater than 0")
        if self.security.auth_backoff_max_seconds < 0:
            raise ConfigurationError("security.auth_backoff_max_seconds must not be negative")

        for label, password in (
            ("password", self.security.password),
            ("read_only_password", self.security.read_only_password),
        ):
            if not password:
                continue
            if "\x00" in password:
                raise ConfigurationError(f"security.{label} must not contain NUL bytes")
            try:
                encoded = password.encode("latin-1")
            except UnicodeEncodeError as exc:
                raise ConfigurationError(
                    f"security.{label} must contain only Latin-1 characters for classic VNC auth"
                ) from exc
            if len(encoded) > 8:
                raise ConfigurationError(
                    f"security.{label} is limited to 8 bytes by classic VNC authentication"
                )
        if (
            self.security.password
            and self.security.read_only_password
            and self.security.password == self.security.read_only_password
        ):
            raise ConfigurationError(
                "security.password and security.read_only_password must be different"
            )
        if self.security.tls_minimum_version not in {"1.2", "1.3"}:
            raise ConfigurationError("security.tls_minimum_version must be '1.2' or '1.3'")

        if self.security.tls_enabled and self.security.vencrypt_enabled:
            raise ConfigurationError(
                "security.tls_enabled (legacy direct TLS) and security.vencrypt_enabled "
                "cannot be enabled at the same time"
            )

        allowed_vencrypt_subtypes = {
            "tls-none", "tlsnone", "tls-vnc", "tlsvnc",
            "x509-none", "x509none", "x509-vnc", "x509vnc",
        }
        normalized_subtypes = tuple(
            item.strip().lower().replace("_", "-")
            for item in self.security.vencrypt_subtypes
        )
        invalid_subtypes = [
            item for item in normalized_subtypes if item not in allowed_vencrypt_subtypes
        ]
        if invalid_subtypes:
            raise ConfigurationError(
                "Unsupported security.vencrypt_subtypes: " + ", ".join(invalid_subtypes)
            )
        anonymous_requested = any(item.startswith("tls") for item in normalized_subtypes)
        x509_requested = any(item.startswith("x509") for item in normalized_subtypes)

        if self.security.vencrypt_enabled:
            # Empty subtype list means automatic X509Vnc/X509None selection.
            needs_x509_identity = not normalized_subtypes or x509_requested
            if needs_x509_identity:
                if not self.security.tls_cert_file or not self.security.tls_key_file:
                    raise ConfigurationError(
                        "VeNCrypt X509 subtypes require tls_cert_file and tls_key_file"
                    )
            if anonymous_requested and not self.security.vencrypt_allow_anonymous_tls:
                raise ConfigurationError(
                    "TLSNone/TLSVnc require security.vencrypt_allow_anonymous_tls=true"
                )

            if normalized_subtypes:
                has_vnc_auth = bool(
                    self.security.password or self.security.read_only_password
                )
                usable_subtypes = []
                for subtype in normalized_subtypes:
                    requires_vnc = subtype in {"tls-vnc", "tlsvnc", "x509-vnc", "x509vnc"}
                    no_auth = subtype in {"tls-none", "tlsnone", "x509-none", "x509none"}
                    if requires_vnc and not has_vnc_auth:
                        continue
                    if (
                        no_auth
                        and has_vnc_auth
                        and not self.security.vencrypt_allow_no_auth_with_password
                    ):
                        continue
                    usable_subtypes.append(subtype)
                if not usable_subtypes:
                    raise ConfigurationError(
                        "security.vencrypt_subtypes contains no subtype usable with "
                        "the current VNC authentication policy"
                    )

        if self.security.tls_enabled or (
            self.security.vencrypt_enabled
            and (
                not normalized_subtypes
                or x509_requested
            )
        ):
            if not self.security.tls_cert_file or not self.security.tls_key_file:
                raise ConfigurationError(
                    "TLS/X509 security requires tls_cert_file and tls_key_file"
                )
            if not Path(self.security.tls_cert_file).is_file():
                raise ConfigurationError(
                    f"TLS certificate file not found: {self.security.tls_cert_file}"
                )
            if not Path(self.security.tls_key_file).is_file():
                raise ConfigurationError(
                    f"TLS key file not found: {self.security.tls_key_file}"
                )

        if self.security.require_encrypted_transport and not (
            self.security.tls_enabled or self.security.vencrypt_enabled
        ):
            raise ConfigurationError(
                "security.require_encrypted_transport requires tls_enabled or vencrypt_enabled"
            )

        if self.websocket.max_message_bytes < self.websocket.max_payload_bytes:
            raise ConfigurationError(
                "websocket.max_message_bytes must be >= websocket.max_payload_bytes"
            )

        has_auth = bool(self.security.password or self.security.read_only_password)
        if not has_auth and not self.security.allow_insecure_no_auth and not _is_loopback_bind(self.host):
            raise ConfigurationError(
                "Refusing unauthenticated VNC on a non-loopback interface. "
                "Configure a password, bind to 127.0.0.1/::1, or explicitly set "
                "security.allow_insecure_no_auth=true."
            )

    def to_dict(self) -> dict[str, Any]:
        values = dict(self.extra)
        values.update({
            "host": self.host,
            "port": self.port,
            "frame_rate": self.frame_rate,
            "lan_frame_rate": self.lan_frame_rate,
            "network_profile_override": self.network_profile_override,
            "scale_factor": self.scale_factor,
            "capture_backend": self.capture_backend,
            "monitor_index": self.monitor_index,
            "capture_all_monitors": self.capture_all_monitors,
            "max_connections": self.max_connections,
            "max_connections_per_ip": self.max_connections_per_ip,
            "max_unauthenticated_connections": self.max_unauthenticated_connections,
            "handshake_timeout": self.handshake_timeout,
            "client_socket_timeout": self.client_socket_timeout,
            "input_control_policy": self.input_control_policy,
            "password": self.security.password,
            "read_only_password": self.security.read_only_password,
            "allow_insecure_no_auth": self.security.allow_insecure_no_auth,
            "tls_enabled": self.security.tls_enabled,
            "tls_cert_file": self.security.tls_cert_file,
            "tls_key_file": self.security.tls_key_file,
            "tls_minimum_version": self.security.tls_minimum_version,
            "vencrypt_enabled": self.security.vencrypt_enabled,
            "vencrypt_subtypes": list(self.security.vencrypt_subtypes),
            "vencrypt_allow_anonymous_tls": self.security.vencrypt_allow_anonymous_tls,
            "vencrypt_allow_no_auth_with_password": self.security.vencrypt_allow_no_auth_with_password,
            "require_encrypted_transport": self.security.require_encrypted_transport,
            "auth_max_failures": self.security.auth_max_failures,
            "auth_failure_window_seconds": self.security.auth_failure_window_seconds,
            "auth_backoff_max_seconds": self.security.auth_backoff_max_seconds,
            "websocket_allowed_origins": list(self.websocket.allowed_origins),
            "websocket_detect_timeout": self.websocket.detect_timeout,
            "websocket_max_handshake_bytes": self.websocket.max_handshake_bytes,
            "websocket_max_payload_bytes": self.websocket.max_payload_bytes,
            "websocket_max_buffer_bytes": self.websocket.max_buffer_bytes,
            "websocket_max_message_bytes": self.websocket.max_message_bytes,
        })
        return values


def _is_loopback_bind(host: str) -> bool:
    text = host.strip().lower()
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _coerce_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else DEFAULT_CONFIG_PATH


def load_config_file(path: str | Path | None = None) -> dict[str, Any]:
    """Load and normalize a TOML configuration file.

    Missing or malformed configuration is intentionally fatal. A VNC server
    must never silently fall back to unauthenticated wildcard defaults.
    """
    config_path = _coerce_path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    if config_path.suffix.lower() != ".toml":
        raise ValueError(f"Unsupported config format for {config_path}; use TOML")

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    normalized = _normalize_config(_flatten_toml_settings(data))
    # Validate the security-sensitive/core values while preserving the flat
    # mapping expected by the existing runtime and public API.
    return ServerSettings.from_mapping(normalized).to_dict()


def _flatten_toml_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the packaged TOML structure into the runtime mapping."""
    flat: dict[str, Any] = {
        key: value for key, value in data.items() if not isinstance(value, dict)
    }

    for section_name in ("server", "features", "limits", "logging", "security"):
        section = data.get(section_name, {})
        if isinstance(section, dict):
            flat.update(section)

    for section_name in ("lan", "websocket"):
        section = data.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            flat[f"{section_name}_{key}"] = value

    network = data.get("network", {})
    if isinstance(network, dict):
        flat.update(network)

    return flat


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)

    encoding_threads = normalized.get("encoding_threads")
    if isinstance(encoding_threads, int) and encoding_threads <= 0:
        normalized["encoding_threads"] = None

    log_file = normalized.get("log_file")
    if isinstance(log_file, str) and not log_file.strip():
        normalized["log_file"] = None

    network_override = normalized.get("network_profile_override")
    if isinstance(network_override, str) and network_override.strip().lower() in {"", "auto", "none"}:
        normalized["network_profile_override"] = None

    return normalized
