"""
Configuration loading and normalization for PyVNCServer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import tomllib


DEFAULT_CONFIG_PATH = Path("config/pyvncserver.toml")
LEGACY_CONFIG_PATH = Path("config.json")


@dataclass(slots=True)
class ServerSettings:
    """Thin settings wrapper used by the packaged API."""

    values: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "ServerSettings":
        return cls(load_config_file(path or DEFAULT_CONFIG_PATH))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)


def _coerce_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else DEFAULT_CONFIG_PATH


def load_config_file(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from TOML or legacy JSON."""
    config_path = _coerce_path(path)
    if not config_path.exists() and config_path == DEFAULT_CONFIG_PATH and LEGACY_CONFIG_PATH.exists():
        config_path = LEGACY_CONFIG_PATH

    if not config_path.exists():
        return {}

    if config_path.suffix.lower() == ".toml":
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        return _normalize_config(_flatten_toml_settings(data))

    with config_path.open("r", encoding="utf-8") as fh:
        return _normalize_config(json.load(fh))


def _flatten_toml_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the packaged TOML structure into the legacy runtime mapping."""
    flat: dict[str, Any] = {
        key: value
        for key, value in data.items()
        if not isinstance(value, dict)
    }

    for section_name in ("server", "features", "limits", "logging"):
        section = data.get(section_name, {})
        if not isinstance(section, dict):
            continue
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
    """Normalize packaged config values to the runtime expectations."""
    normalized = dict(config)

    encoding_threads = normalized.get("encoding_threads")
    if isinstance(encoding_threads, int) and encoding_threads <= 0:
        normalized["encoding_threads"] = None

    log_file = normalized.get("log_file")
    if isinstance(log_file, str) and not log_file.strip():
        normalized["log_file"] = None

    return normalized
