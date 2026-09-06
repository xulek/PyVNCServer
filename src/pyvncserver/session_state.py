"""Per-client runtime state for a VNC session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vnc_lib.change_detector import AdaptiveChangeDetector
from vnc_lib.cursor import CursorEncoder, SystemCursorCapture
from vnc_lib.encodings import EncoderManager
from vnc_lib.metrics import ConnectionMetrics
from vnc_lib.server_utils import NetworkProfile


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
