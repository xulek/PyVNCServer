"""Per-client runtime state for a VNC session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pyvncserver._core.change_detector import AdaptiveChangeDetector
from pyvncserver._core.cursor import CursorEncoder, SystemCursorCapture
from pyvncserver._core.encodings import EncoderManager
from pyvncserver._core.metrics import ConnectionMetrics
from pyvncserver._core.server_utils import NetworkProfile


@dataclass(slots=True)
class ClientSessionState:
    """Mutable state negotiated independently for each connected client."""

    client_id: str
    pixel_format: dict[str, Any]
    encodings: list[int]
    fb_width: int
    fb_height: int
    encoder_manager: EncoderManager
    network_profile: NetworkProfile
    view_only: bool = False
    change_detector: AdaptiveChangeDetector | None = None
    conn_metrics: ConnectionMetrics | None = None
    cursor_capture: SystemCursorCapture | None = None
    cursor_encoder: CursorEncoder | None = None
    parallel_encoder: Any = None
    last_pointer_pos: tuple[int, int] | None = None
    last_frame_generation: int = -1
