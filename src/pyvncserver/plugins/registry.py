"""Typed plugin registry used by the embeddable server API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .interfaces import CaptureBackendPlugin, EncodingPlugin, SecurityPlugin


_RESERVED_SECURITY_TYPES = {1, 2, 16, 19}


@dataclass(slots=True)
class PluginManager:
    """Holds process-local plugin registrations for one server instance.

    Registries are explicit and per-server; importing a plugin never mutates a
    global registry. This keeps tests and multiple embedded servers isolated.
    """

    _capture: dict[str, CaptureBackendPlugin] = field(default_factory=dict)
    _encodings: dict[int, EncodingPlugin] = field(default_factory=dict)
    _security: dict[int, SecurityPlugin] = field(default_factory=dict)

    def register_capture(self, plugin: CaptureBackendPlugin) -> None:
        name = str(plugin.name).strip().lower()
        if not name or name == "auto":
            raise ValueError("capture plugin name must be non-empty and cannot be 'auto'")
        if name in {"dxcam", "mss", "pil"} or name in self._capture:
            raise ValueError(f"capture plugin name is already registered/reserved: {name}")
        self._capture[name] = plugin

    def register_encoding(self, plugin: EncodingPlugin) -> None:
        encoding_id = int(plugin.encoding_id)
        if encoding_id in {0, 1, 2, 5, 6, 7, 16, 21, 50} or encoding_id in self._encodings:
            raise ValueError(f"encoding id is already registered/reserved: {encoding_id}")
        self._encodings[encoding_id] = plugin

    def register_security(self, plugin: SecurityPlugin) -> None:
        security_type = int(plugin.security_type)
        if not 1 <= security_type <= 255:
            raise ValueError("RFB security type must fit in one byte")
        if security_type in _RESERVED_SECURITY_TYPES or security_type in self._security:
            raise ValueError(f"security type is already registered/reserved: {security_type}")
        self._security[security_type] = plugin

    def capture_factories(self) -> dict[str, Callable[[object], object]]:
        return {
            name: plugin.create_backend
            for name, plugin in self._capture.items()
        }

    def create_encoders(self) -> dict[int, object]:
        return {
            encoding_id: plugin.create_encoder()
            for encoding_id, plugin in self._encodings.items()
        }

    def security_plugins(self) -> dict[int, SecurityPlugin]:
        return dict(self._security)

    @property
    def capture_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capture))

    @property
    def encoding_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._encodings))

    @property
    def security_types(self) -> tuple[int, ...]:
        return tuple(sorted(self._security))

    def extend(
        self,
        *,
        capture: Iterable[CaptureBackendPlugin] = (),
        encodings: Iterable[EncodingPlugin] = (),
        security: Iterable[SecurityPlugin] = (),
    ) -> "PluginManager":
        for plugin in capture:
            self.register_capture(plugin)
        for plugin in encodings:
            self.register_encoding(plugin)
        for plugin in security:
            self.register_security(plugin)
        return self
