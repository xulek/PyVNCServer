"""
Session Recording and Playback Module

This module provides functionality to record VNC sessions and play them back.
Records all VNC protocol messages with timestamps for audit trails and debugging.

Uses Python 3.13 features:
- Type parameter syntax for better type safety
- Pattern matching for event handling
- Exception groups for multi-error handling
"""

import json
import struct
import time
import gzip
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Protocol, Self
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import IntEnum, auto

from .types import Rectangle
from .exceptions import ProtocolError


class EventType(IntEnum):
    """Types of events that can be recorded in a session."""

    HANDSHAKE = auto()
    AUTH = auto()
    INIT = auto()
    FRAMEBUFFER_UPDATE = auto()
    SET_ENCODINGS = auto()
    KEY_EVENT = auto()
    POINTER_EVENT = auto()
    CLIENT_CUT_TEXT = auto()
    SERVER_CUT_TEXT = auto()
    SET_COLOUR_MAP_ENTRIES = auto()
    BELL = auto()
    DESKTOP_RESIZE = auto()
    CURSOR_UPDATE = auto()
    ERROR = auto()


@dataclass(slots=True, frozen=True)
class SessionEvent:
    """Represents a single recorded event in a VNC session."""

    timestamp: float
    event_type: EventType
    data: bytes
    metadata: dict[str, str | int | float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp,
            'event_type': self.event_type.name,
            'data': self.data.hex(),
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        """Create event from dictionary."""
        return cls(
            timestamp=data['timestamp'],
            event_type=EventType[data['event_type']],
            data=bytes.fromhex(data['data']),
            metadata=data.get('metadata', {})
        )


class SessionRecorder:
    """
    Records VNC session events to a file for later playback and analysis.

    Uses gzip compression to save disk space.
    Supports context manager protocol for automatic cleanup.
    """

    __slots__ = ('_file_path', '_file_handle', '_start_time',
                 '_event_count', '_compress', '_session_id')

    def __init__(self, file_path: str | Path, compress: bool = True):
        self._file_path = Path(file_path)
        self._file_handle: BinaryIO | None = None
        self._start_time: float = 0.0
        self._event_count: int = 0
        self._compress = compress
        self._session_id = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

    def __enter__(self) -> Self:
        """Start recording session."""
        self._start_time = time.monotonic()

        # Create parent directories if needed
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Open file with optional compression
        if self._compress:
            self._file_handle = gzip.open(self._file_path, 'wb', compresslevel=6)
        else:
            self._file_handle = open(self._file_path, 'wb')

        # Write session header
        header = self._create_header()
        self._write_line(header)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Stop recording and close file."""
        if self._file_handle:
            # Write session footer with statistics
            footer = self._create_footer()
            self._write_line(footer)

            self._file_handle.close()
            self._file_handle = None

        return False

    def _create_header(self) -> dict:
        """Create session header with metadata."""
        return {
            'version': '1.0',
            'session_id': self._session_id,
            'start_time': datetime.now(timezone.utc).isoformat(),
            'compressed': self._compress
        }

    def _create_footer(self) -> dict:
        """Create session footer with statistics."""
        duration = time.monotonic() - self._start_time
        return {
            'end_time': datetime.now(timezone.utc).isoformat(),
            'duration_seconds': round(duration, 3),
            'event_count': self._event_count
        }

    def _write_line(self, data: dict) -> None:
        """Write a JSON line to the file."""
        if not self._file_handle:
            raise RuntimeError("Recorder not started")

        line = json.dumps(data, separators=(',', ':'))
        self._file_handle.write(line.encode('utf-8'))
        self._file_handle.write(b'\n')

    def record_event(
        self,
        event_type: EventType,
        data: bytes,
        **metadata: str | int | float
    ) -> None:
        """Record a single VNC event."""
        if not self._file_handle:
            raise RuntimeError("Recorder not started")

        timestamp = time.monotonic() - self._start_time
        event = SessionEvent(timestamp, event_type, data, dict(metadata))

        self._write_line(event.to_dict())
        self._event_count += 1

    def record_handshake(self, protocol_version: bytes) -> None:
        """Record protocol handshake."""
        self.record_event(
            EventType.HANDSHAKE,
            protocol_version,
            version=protocol_version.decode('ascii', errors='replace')
        )

    def record_auth(self, auth_type: int, success: bool) -> None:
        """Record authentication attempt."""
        self.record_event(
            EventType.AUTH,
            struct.pack('!I', auth_type),
            auth_type=auth_type,
            success=int(success)
        )

    def record_init(self, width: int, height: int, name: str) -> None:
        """Record client initialization."""
        self.record_event(
            EventType.INIT,
            name.encode('utf-8'),
            width=width,
            height=height
        )

    def record_framebuffer_update(
        self,
        rectangles: list[Rectangle],
        encoding: int,
        data_size: int
    ) -> None:
        """Record framebuffer update."""
        rects_data = struct.pack('!H', len(rectangles))
        for rect in rectangles:
            rects_data += struct.pack('!HHHH', rect.x, rect.y, rect.width, rect.height)

        self.record_event(
            EventType.FRAMEBUFFER_UPDATE,
            rects_data,
            encoding=encoding,
            data_size=data_size,
            rect_count=len(rectangles)
        )

    def record_key_event(self, key: int, down: bool) -> None:
        """Record keyboard event."""
        self.record_event(
            EventType.KEY_EVENT,
            struct.pack('!IB', key, int(down)),
            key=key,
            down=int(down)
        )

    def record_pointer_event(self, x: int, y: int, button_mask: int) -> None:
        """Record mouse/pointer event."""
        self.record_event(
            EventType.POINTER_EVENT,
            struct.pack('!HHB', x, y, button_mask),
            x=x,
            y=y,
            buttons=button_mask
        )

    def record_error(self, error_msg: str) -> None:
        """Record an error that occurred during session."""
        self.record_event(
            EventType.ERROR,
            error_msg.encode('utf-8'),
            message=error_msg
        )

    @property
    def event_count(self) -> int:
        """Get number of events recorded so far."""
        return self._event_count

    @property
    def duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._start_time == 0:
            return 0.0
        return time.monotonic() - self._start_time


class SessionPlayer:
    """
    Plays back a recorded VNC session.

    Allows playback at different speeds and filtering by event types.
    """

    __slots__ = ('_file_path', '_file_handle', '_header', '_events',
                 '_current_index', '_start_time')

    def __init__(self, file_path: str | Path):
        self._file_path = Path(file_path)
        self._file_handle: BinaryIO | None = None
        self._header: dict | None = None
        self._events: list[SessionEvent] = []
        self._current_index: int = 0
        self._start_time: float = 0.0

    def __enter__(self) -> Self:
        """Start playback session."""
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Stop playback and cleanup."""
        self._events.clear()
        self._current_index = 0
        return False

    def load(self) -> None:
        """Load session from file."""
        if not self._file_path.exists():
            raise FileNotFoundError(f"Session file not found: {self._file_path}")

        # Detect if file is compressed
        is_compressed = self._file_path.suffix == '.gz' or self._is_gzipped()

        if is_compressed:
            file_handle = gzip.open(self._file_path, 'rb')
        else:
            file_handle = open(self._file_path, 'rb')

        try:
            lines = file_handle.read().decode('utf-8').strip().split('\n')

            if len(lines) < 2:
                raise ProtocolError("Invalid session file: too few lines")

            # Parse header
            self._header = json.loads(lines[0])

            # Parse events (skip header and footer)
            self._events = []
            for line in lines[1:-1]:
                if line.strip():
                    event_data = json.loads(line)
                    self._events.append(SessionEvent.from_dict(event_data))

            # Parse footer (optional, for statistics)
            if len(lines) > 1:
                footer = json.loads(lines[-1])
                # Footer contains statistics, could be used for validation

        finally:
            file_handle.close()

    def _is_gzipped(self) -> bool:
        """Check if file is gzip compressed by reading magic bytes."""
        with open(self._file_path, 'rb') as f:
            magic = f.read(2)
            return magic == b'\x1f\x8b'

    def play(
        self,
        speed: float = 1.0,
        event_filter: set[EventType] | None = None
    ) -> Iterator[SessionEvent]:
        """
        Play back the session events in real-time.

        Args:
            speed: Playback speed multiplier (1.0 = real-time)
            event_filter: Only yield events of these types (None = all events)

        Yields:
            SessionEvent objects in chronological order
        """
        if not self._events:
            return

        self._start_time = time.monotonic()
        self._current_index = 0

        for event in self._events:
            # Filter events if requested
            if event_filter and event.event_type not in event_filter:
                continue

            # Wait until event should be played
            target_time = event.timestamp / speed
            elapsed = time.monotonic() - self._start_time
            sleep_time = target_time - elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)

            yield event
            self._current_index += 1

    def get_events(
        self,
        event_filter: set[EventType] | None = None
    ) -> list[SessionEvent]:
        """Get all events, optionally filtered by type."""
        if event_filter:
            return [e for e in self._events if e.event_type in event_filter]
        return self._events.copy()

    def get_statistics(self) -> dict[str, int | float]:
        """Get session statistics."""
        if not self._events:
            return {}

        event_counts = {}
        for event in self._events:
            event_type = event.event_type.name
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        duration = self._events[-1].timestamp if self._events else 0.0

        return {
            'total_events': len(self._events),
            'duration_seconds': round(duration, 3),
            'events_per_second': round(len(self._events) / duration, 2) if duration > 0 else 0,
            'event_counts': event_counts,
            'session_id': self._header.get('session_id', 'unknown') if self._header else 'unknown',
            'start_time': self._header.get('start_time', 'unknown') if self._header else 'unknown'
        }

    def seek(self, timestamp: float) -> None:
        """Seek to a specific timestamp in the recording."""
        for i, event in enumerate(self._events):
            if event.timestamp >= timestamp:
                self._current_index = i
                return
        self._current_index = len(self._events)

    def reset(self) -> None:
        """Reset playback to the beginning."""
        self._current_index = 0
        self._start_time = 0.0

    @property
    def duration(self) -> float:
        """Get total duration of the recorded session."""
        if not self._events:
            return 0.0
        return self._events[-1].timestamp

    @property
    def event_count(self) -> int:
        """Get total number of events in the recording."""
        return len(self._events)
