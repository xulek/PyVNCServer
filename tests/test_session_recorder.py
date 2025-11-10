"""Tests for session recording and playback functionality."""

import pytest
import tempfile
import time
from pathlib import Path

from vnc_lib.session_recorder import (
    SessionRecorder, SessionPlayer, SessionEvent, EventType
)
from vnc_lib.types import Rectangle


class TestSessionRecorder:
    """Test SessionRecorder functionality."""

    def test_recorder_context_manager(self):
        """Test that recorder works with context manager."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            with SessionRecorder(session_file) as recorder:
                assert recorder.event_count == 0
                assert recorder.duration >= 0

            assert session_file.exists()
        finally:
            session_file.unlink(missing_ok=True)

    def test_record_handshake(self):
        """Test recording handshake events."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            with SessionRecorder(session_file) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                assert recorder.event_count == 1

            # Verify file was created
            assert session_file.exists()
            assert session_file.stat().st_size > 0
        finally:
            session_file.unlink(missing_ok=True)

    def test_record_multiple_events(self):
        """Test recording multiple types of events."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            with SessionRecorder(session_file) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                recorder.record_auth(1, True)
                recorder.record_init(1024, 768, 'Test Desktop')
                recorder.record_key_event(65, True)  # 'A' key down
                recorder.record_pointer_event(100, 200, 1)

                assert recorder.event_count == 5

            assert session_file.exists()
        finally:
            session_file.unlink(missing_ok=True)

    def test_record_framebuffer_update(self):
        """Test recording framebuffer update events."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            with SessionRecorder(session_file) as recorder:
                # Rectangle is a tuple type alias
                rects: list[Rectangle] = [
                    (0, 0, 100, 100),
                    (100, 100, 50, 50)
                ]
                recorder.record_framebuffer_update(rects, encoding=0, data_size=10000)

                assert recorder.event_count == 1

            assert session_file.exists()
        finally:
            session_file.unlink(missing_ok=True)

    def test_record_error(self):
        """Test recording error events."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            with SessionRecorder(session_file) as recorder:
                recorder.record_error('Test error message')
                assert recorder.event_count == 1

            assert session_file.exists()
        finally:
            session_file.unlink(missing_ok=True)

    def test_uncompressed_recording(self):
        """Test recording without compression."""
        with tempfile.NamedTemporaryFile(suffix='.session', delete=False) as f:
            session_file = Path(f.name)

        try:
            with SessionRecorder(session_file, compress=False) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                recorder.record_auth(1, True)

            assert session_file.exists()
            # Uncompressed file should be larger
            assert session_file.stat().st_size > 50
        finally:
            session_file.unlink(missing_ok=True)


class TestSessionPlayer:
    """Test SessionPlayer functionality."""

    def test_player_load_session(self):
        """Test loading a recorded session."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record a session
            with SessionRecorder(session_file) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                recorder.record_auth(1, True)
                recorder.record_init(1024, 768, 'Test')

            # Load and play it back
            player = SessionPlayer(session_file)
            player.load()

            assert player.event_count == 3
            assert player.duration > 0

        finally:
            session_file.unlink(missing_ok=True)

    def test_player_get_events(self):
        """Test getting events from player."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record a session
            with SessionRecorder(session_file) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                recorder.record_auth(1, True)
                recorder.record_key_event(65, True)

            # Load and get events
            player = SessionPlayer(session_file)
            player.load()

            events = player.get_events()
            assert len(events) == 3
            assert events[0].event_type == EventType.HANDSHAKE
            assert events[1].event_type == EventType.AUTH
            assert events[2].event_type == EventType.KEY_EVENT

        finally:
            session_file.unlink(missing_ok=True)

    def test_player_filter_events(self):
        """Test filtering events by type."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record mixed events
            with SessionRecorder(session_file) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                recorder.record_key_event(65, True)
                recorder.record_pointer_event(100, 200, 1)
                recorder.record_key_event(66, True)

            # Load and filter
            player = SessionPlayer(session_file)
            player.load()

            key_events = player.get_events({EventType.KEY_EVENT})
            assert len(key_events) == 2
            assert all(e.event_type == EventType.KEY_EVENT for e in key_events)

        finally:
            session_file.unlink(missing_ok=True)

    def test_player_statistics(self):
        """Test getting session statistics."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record a session
            with SessionRecorder(session_file) as recorder:
                recorder.record_handshake(b'RFB 003.008\n')
                recorder.record_key_event(65, True)
                recorder.record_key_event(66, True)
                recorder.record_pointer_event(100, 200, 1)

            # Get statistics
            player = SessionPlayer(session_file)
            player.load()

            stats = player.get_statistics()
            assert stats['total_events'] == 4
            assert stats['duration_seconds'] >= 0
            assert 'HANDSHAKE' in stats['event_counts']
            assert stats['event_counts']['KEY_EVENT'] == 2

        finally:
            session_file.unlink(missing_ok=True)

    def test_player_seek(self):
        """Test seeking to a specific timestamp."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record events with delays
            with SessionRecorder(session_file) as recorder:
                recorder.record_key_event(65, True)
                time.sleep(0.01)
                recorder.record_key_event(66, True)
                time.sleep(0.01)
                recorder.record_key_event(67, True)

            # Load and seek
            player = SessionPlayer(session_file)
            player.load()

            events = player.get_events()
            if len(events) > 1:
                mid_timestamp = events[1].timestamp
                player.seek(mid_timestamp)

        finally:
            session_file.unlink(missing_ok=True)

    def test_player_reset(self):
        """Test resetting player to beginning."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record a session
            with SessionRecorder(session_file) as recorder:
                recorder.record_key_event(65, True)
                recorder.record_key_event(66, True)

            # Load, seek, then reset
            player = SessionPlayer(session_file)
            player.load()

            events = player.get_events()
            if len(events) > 0:
                player.seek(events[-1].timestamp)
                player.reset()

        finally:
            session_file.unlink(missing_ok=True)

    def test_player_context_manager(self):
        """Test player context manager."""
        with tempfile.NamedTemporaryFile(suffix='.session.gz', delete=False) as f:
            session_file = Path(f.name)

        try:
            # Record a session
            with SessionRecorder(session_file) as recorder:
                recorder.record_key_event(65, True)

            # Use context manager
            with SessionPlayer(session_file) as player:
                assert player.event_count == 1

        finally:
            session_file.unlink(missing_ok=True)


class TestSessionEvent:
    """Test SessionEvent functionality."""

    def test_event_creation(self):
        """Test creating a session event."""
        event = SessionEvent(
            timestamp=1.0,
            event_type=EventType.KEY_EVENT,
            data=b'\x00\x00\x00A\x01',
            metadata={'key': 65, 'down': 1}
        )

        assert event.timestamp == 1.0
        assert event.event_type == EventType.KEY_EVENT
        assert event.metadata['key'] == 65

    def test_event_serialization(self):
        """Test event to_dict and from_dict."""
        original = SessionEvent(
            timestamp=1.5,
            event_type=EventType.POINTER_EVENT,
            data=b'\x00d\x00\xc8\x01',
            metadata={'x': 100, 'y': 200}
        )

        # Convert to dict and back
        event_dict = original.to_dict()
        restored = SessionEvent.from_dict(event_dict)

        assert restored.timestamp == original.timestamp
        assert restored.event_type == original.event_type
        assert restored.data == original.data
        assert restored.metadata == original.metadata
