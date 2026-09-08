"""Operational diagnostics used by the PyVNCServer 3.7 CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.util
import json
import os
from pathlib import Path
import platform
import socket
import ssl
import sys
from typing import Any

from ._version import __version__
from .config import DEFAULT_CONFIG_PATH, ServerSettings, load_config_file


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DoctorReport:
    version: str
    platform: str
    python: str
    config_path: str
    checks: tuple[DiagnosticCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "platform": self.platform,
            "python": self.python,
            "config_path": self.config_path,
            "checks": [check.to_dict() for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _module_check(module: str, label: str, required: bool = False) -> DiagnosticCheck:
    available = importlib.util.find_spec(module) is not None
    return DiagnosticCheck(
        name=label,
        ok=available,
        detail="available" if available else "not installed",
        required=required,
    )


def _port_check(host: str, port: int) -> DiagnosticCheck:
    family = socket.AF_INET6 if ":" in host and host != "localhost" else socket.AF_INET
    bind_host = host
    if host == "localhost":
        bind_host = "127.0.0.1"
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((bind_host, int(port)))
        return DiagnosticCheck("listen-port", True, f"{host}:{port} is available")
    except OSError as exc:
        return DiagnosticCheck("listen-port", False, f"{host}:{port}: {exc}")


def _tls_check(settings: ServerSettings) -> DiagnosticCheck:
    sec = settings.security
    if not (sec.tls_enabled or sec.vencrypt_enabled):
        return DiagnosticCheck("tls-identity", True, "TLS/VeNCrypt disabled", required=False)

    normalized = tuple(item.lower().replace("_", "-") for item in sec.vencrypt_subtypes)
    x509_needed = sec.tls_enabled or not normalized or any(item.startswith("x509") for item in normalized)
    if not x509_needed:
        return DiagnosticCheck(
            "tls-identity", True, "anonymous VeNCrypt TLS requested", required=False
        )

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = (
            ssl.TLSVersion.TLSv1_3
            if sec.tls_minimum_version == "1.3"
            else ssl.TLSVersion.TLSv1_2
        )
        context.load_cert_chain(sec.tls_cert_file, sec.tls_key_file)
        return DiagnosticCheck(
            "tls-identity", True, f"certificate/key load successfully; TLS >= {sec.tls_minimum_version}"
        )
    except Exception as exc:
        return DiagnosticCheck("tls-identity", False, str(exc))


def run_doctor(config_path: str | Path = DEFAULT_CONFIG_PATH) -> DoctorReport:
    path = Path(config_path)
    checks: list[DiagnosticCheck] = []
    settings: ServerSettings | None = None
    try:
        mapping = load_config_file(path)
        settings = ServerSettings.from_mapping(mapping)
        checks.append(DiagnosticCheck("configuration", True, "valid TOML configuration"))
    except Exception as exc:
        checks.append(DiagnosticCheck("configuration", False, str(exc)))

    has_crypto = importlib.util.find_spec("Crypto") is not None
    has_pillow = importlib.util.find_spec("PIL") is not None
    has_mss = importlib.util.find_spec("mss") is not None
    has_dxcam = importlib.util.find_spec("dxcam") is not None
    has_numpy = importlib.util.find_spec("numpy") is not None
    has_av = importlib.util.find_spec("av") is not None

    needs_crypto = bool(settings and (settings.security.password or settings.security.read_only_password))
    checks.append(DiagnosticCheck("pycryptodome", has_crypto, "available" if has_crypto else "not installed", needs_crypto))
    checks.append(DiagnosticCheck("Pillow", has_pillow, "available" if has_pillow else "not installed", bool(settings and settings.capture_backend == "pil")))
    checks.append(DiagnosticCheck("MSS", has_mss, "available" if has_mss else "not installed", bool(settings and (settings.capture_backend == "mss" or settings.capture_all_monitors))))
    checks.append(DiagnosticCheck("NumPy", has_numpy, "available" if has_numpy else "not installed", False))
    checks.append(DiagnosticCheck("DXCam", has_dxcam, "available" if has_dxcam else "not installed", bool(settings and settings.capture_backend == "dxcam")))
    checks.append(DiagnosticCheck("PyAV/H.264", has_av, "available" if has_av else "not installed", False))

    if settings is not None:
        if settings.capture_backend == "auto":
            auto_capture_ok = has_pillow or has_mss or (os.name == "nt" and has_dxcam)
            checks.append(DiagnosticCheck(
                "capture-runtime", auto_capture_ok,
                "at least one capture backend is importable" if auto_capture_ok else "no capture backend is importable",
            ))
        checks.append(_port_check(settings.host, settings.port))
        if bool(settings.extra.get("observability_prometheus_enabled", False)):
            obs_host = str(settings.extra.get("observability_prometheus_host", "127.0.0.1"))
            obs_port = int(settings.extra.get("observability_prometheus_port", 9100))
            checks.append(_port_check(obs_host, obs_port))
        checks.append(_tls_check(settings))
        if settings.capture_backend == "dxcam" and os.name != "nt":
            checks.append(DiagnosticCheck(
                "capture-backend", False, "DXCam was explicitly selected on a non-Windows platform"
            ))
        elif settings.capture_backend not in {"auto", "dxcam", "mss", "pil"}:
            checks.append(DiagnosticCheck(
                "capture-backend", False, f"unknown backend: {settings.capture_backend}"
            ))
        else:
            checks.append(DiagnosticCheck(
                "capture-backend", True, f"configured backend: {settings.capture_backend}"
            ))

    return DoctorReport(
        version=__version__,
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        python=sys.version.split()[0],
        config_path=str(path),
        checks=tuple(checks),
    )


def format_doctor_report(report: DoctorReport) -> str:
    lines = [
        f"PyVNCServer {report.version}",
        f"Python:   {report.python}",
        f"Platform: {report.platform}",
        f"Config:   {report.config_path}",
        "",
    ]
    for check in report.checks:
        marker = "OK" if check.ok else ("WARN" if not check.required else "FAIL")
        lines.append(f"[{marker:4}] {check.name:18} {check.detail}")
    lines.extend(["", f"Result: {'PASS' if report.ok else 'FAIL'}"])
    return "\n".join(lines)


def runtime_info() -> dict[str, Any]:
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "default_config": str(DEFAULT_CONFIG_PATH),
        "optional": {
            "dxcam": importlib.util.find_spec("dxcam") is not None,
            "numpy": importlib.util.find_spec("numpy") is not None,
            "av": importlib.util.find_spec("av") is not None,
        },
    }
