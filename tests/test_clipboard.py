"""Tests for clipboard synchronization functionality."""

import pytest
import struct

from vnc_lib.clipboard import (
    ClipboardManager, ClipboardData, ClipboardHistory,
    ClipboardFormat, sanitize_clipboard_text, estimate_clipboard_encoding
)


class TestClipboardData:
    """Test ClipboardData functionality."""

    def test_create_from_text(self):
        """Test creating clipboard data from text."""
        data = ClipboardData.from_text("Hello, VNC!")

        assert data.format == ClipboardFormat.TEXT
        assert data.text == "Hello, VNC!"
        assert data.encoding == 'latin-1'

    def test_to_vnc_message(self):
        """Test converting to VNC ServerCutText message."""
        data = ClipboardData.from_text("Test")
        message = data.to_vnc_message()

        # Check message format
        assert message[0] == 3  # ServerCutText message type
        assert message[1:4] == b'\x00\x00\x00'  # Padding
        length = struct.unpack('!I', message[4:8])[0]
        assert length == 4
        assert message[8:] == b'Test'

    def test_from_vnc_message(self):
        """Test parsing VNC ClientCutText message."""
        # Create a ClientCutText message
        text = b'Hello'
        message = bytearray()
        message.append(6)  # ClientCutText message type
        message.extend(b'\x00\x00\x00')  # Padding
        message.extend(struct.pack('!I', len(text)))
        message.extend(text)

        data = ClipboardData.from_vnc_message(bytes(message))

        assert data.format == ClipboardFormat.TEXT
        assert data.content == b'Hello'
        assert data.text == 'Hello'

    def test_text_property(self):
        """Test text property decoding."""
        data = ClipboardData(
            format=ClipboardFormat.TEXT,
            content=b'Test text',
            encoding='utf-8'
        )

        assert data.text == 'Test text'

    def test_invalid_message_too_short(self):
        """Test parsing message that's too short."""
        with pytest.raises(ValueError, match="too short"):
            ClipboardData.from_vnc_message(b'\x06\x00')

    def test_invalid_message_type(self):
        """Test parsing message with wrong type."""
        message = b'\x05\x00\x00\x00\x00\x00\x00\x05Hello'
        with pytest.raises(ValueError, match="Invalid clipboard message type"):
            ClipboardData.from_vnc_message(message)


class TestClipboardManager:
    """Test ClipboardManager functionality."""

    def test_manager_creation(self):
        """Test creating clipboard manager."""
        manager = ClipboardManager()

        assert manager.is_enabled
        assert manager.get_client_clipboard_text() is None
        assert manager.get_server_clipboard_text() is None

    def test_enable_disable(self):
        """Test enabling and disabling clipboard sync."""
        manager = ClipboardManager()

        assert manager.is_enabled

        manager.disable()
        assert not manager.is_enabled

        manager.enable()
        assert manager.is_enabled

    def test_handle_client_cut_text(self):
        """Test handling client clipboard update."""
        manager = ClipboardManager()

        # Create ClientCutText message
        text = b'Client clipboard'
        message = bytearray()
        message.append(6)
        message.extend(b'\x00\x00\x00')
        message.extend(struct.pack('!I', len(text)))
        message.extend(text)

        manager.handle_client_cut_text(bytes(message))

        assert manager.get_client_clipboard_text() == 'Client clipboard'

    def test_set_server_clipboard(self):
        """Test setting server clipboard."""
        manager = ClipboardManager()

        message = manager.set_server_clipboard('Server text')

        assert message is not None
        assert message[0] == 3  # ServerCutText type
        assert manager.get_server_clipboard_text() == 'Server text'

    def test_server_clipboard_unchanged(self):
        """Test that unchanged clipboard returns None."""
        manager = ClipboardManager()

        # Set clipboard first time
        msg1 = manager.set_server_clipboard('Same text')
        assert msg1 is not None

        # Set same text again
        msg2 = manager.set_server_clipboard('Same text')
        assert msg2 is None

    def test_clipboard_size_limit(self):
        """Test clipboard size limit enforcement."""
        manager = ClipboardManager(max_size=100)

        # Try to set clipboard larger than limit
        large_text = 'X' * 200
        message = manager.set_server_clipboard(large_text)

        assert message is None  # Should fail silently

    def test_clipboard_disabled(self):
        """Test clipboard operations when disabled."""
        manager = ClipboardManager()
        manager.disable()

        # Try to set clipboard while disabled
        message = manager.set_server_clipboard('Test')
        assert message is None

        # Create ClientCutText message
        text = b'Client text'
        client_msg = bytearray()
        client_msg.append(6)
        client_msg.extend(b'\x00\x00\x00')
        client_msg.extend(struct.pack('!I', len(text)))
        client_msg.extend(text)

        # Try to handle client clipboard while disabled
        manager.handle_client_cut_text(bytes(client_msg))
        assert manager.get_client_clipboard_text() is None

    def test_clipboard_callbacks(self):
        """Test clipboard update callbacks."""
        manager = ClipboardManager()

        client_updates = []
        server_updates = []

        def on_client_update(data):
            client_updates.append(data.text)

        def on_server_update(data):
            server_updates.append(data.text)

        manager.on_client_update(on_client_update)
        manager.on_server_update(on_server_update)

        # Trigger server update
        manager.set_server_clipboard('Server text')
        assert len(server_updates) == 1
        assert server_updates[0] == 'Server text'

        # Trigger client update
        text = b'Client text'
        message = bytearray()
        message.append(6)
        message.extend(b'\x00\x00\x00')
        message.extend(struct.pack('!I', len(text)))
        message.extend(text)

        manager.handle_client_cut_text(bytes(message))
        assert len(client_updates) == 1
        assert client_updates[0] == 'Client text'

    def test_clear_callbacks(self):
        """Test clearing callbacks."""
        manager = ClipboardManager()

        manager.on_client_update(lambda x: None)
        manager.on_server_update(lambda x: None)

        manager.clear_callbacks()

        stats = manager.get_stats()
        assert stats['callback_count'] == 0

    def test_clear_clipboard(self):
        """Test clearing clipboard content."""
        manager = ClipboardManager()

        manager.set_server_clipboard('Test')
        assert manager.get_server_clipboard_text() == 'Test'

        manager.clear()
        assert manager.get_server_clipboard_text() is None

    def test_get_stats(self):
        """Test getting clipboard statistics."""
        manager = ClipboardManager(max_size=2048)

        manager.set_server_clipboard('Server text')

        stats = manager.get_stats()

        assert stats['enabled'] is True
        assert stats['max_size'] == 2048
        assert stats['server_content_size'] > 0
        assert stats['server_timestamp'] is not None


class TestClipboardHistory:
    """Test ClipboardHistory functionality."""

    def test_history_creation(self):
        """Test creating clipboard history."""
        history = ClipboardHistory(max_entries=50)

        assert history.get_stats()['entry_count'] == 0
        assert history.get_stats()['max_entries'] == 50

    def test_add_entry(self):
        """Test adding clipboard entries."""
        history = ClipboardHistory()

        data1 = ClipboardData.from_text('First')
        data2 = ClipboardData.from_text('Second')

        history.add(data1)
        history.add(data2)

        stats = history.get_stats()
        assert stats['entry_count'] == 2

    def test_get_recent(self):
        """Test getting recent entries."""
        history = ClipboardHistory()

        for i in range(5):
            data = ClipboardData.from_text(f'Entry {i}')
            history.add(data)

        recent = history.get_recent(3)
        assert len(recent) == 3
        assert recent[-1].text == 'Entry 4'

    def test_circular_buffer(self):
        """Test that history uses circular buffer."""
        history = ClipboardHistory(max_entries=3)

        # Add more entries than max
        for i in range(5):
            data = ClipboardData.from_text(f'Entry {i}')
            history.add(data)

        stats = history.get_stats()
        assert stats['entry_count'] == 3

    def test_clear_history(self):
        """Test clearing history."""
        history = ClipboardHistory()

        for i in range(5):
            data = ClipboardData.from_text(f'Entry {i}')
            history.add(data)

        history.clear()

        stats = history.get_stats()
        assert stats['entry_count'] == 0

    def test_get_stats(self):
        """Test getting history statistics."""
        history = ClipboardHistory(max_entries=100)

        data1 = ClipboardData.from_text('Short')
        data2 = ClipboardData.from_text('A longer piece of text')

        history.add(data1)
        history.add(data2)

        stats = history.get_stats()
        assert stats['entry_count'] == 2
        assert stats['total_size_bytes'] > 0
        assert stats['average_size_bytes'] > 0


class TestClipboardUtilities:
    """Test clipboard utility functions."""

    def test_sanitize_clipboard_text(self):
        """Test sanitizing clipboard text."""
        # Test with control characters
        text = "Hello\x00World\x01Test"
        sanitized = sanitize_clipboard_text(text)
        assert '\x00' not in sanitized
        assert '\x01' not in sanitized

        # Test with newlines (should be preserved)
        text = "Line1\nLine2\rLine3\r\nLine4"
        sanitized = sanitize_clipboard_text(text)
        assert '\n' in sanitized
        assert '\r' not in sanitized  # Should be normalized

    def test_sanitize_length_limit(self):
        """Test length limiting."""
        long_text = 'X' * 2000
        sanitized = sanitize_clipboard_text(long_text, max_length=100)
        assert len(sanitized) == 100

    def test_sanitize_line_ending_normalization(self):
        """Test line ending normalization."""
        text = "Line1\r\nLine2\rLine3\nLine4"
        sanitized = sanitize_clipboard_text(text)

        # All should be normalized to \n
        assert '\r\n' not in sanitized
        assert '\r' not in sanitized
        assert sanitized.count('\n') == 3

    def test_estimate_encoding_utf8(self):
        """Test encoding estimation for UTF-8."""
        utf8_data = 'Hello 世界'.encode('utf-8')
        encoding = estimate_clipboard_encoding(utf8_data)
        assert encoding == 'utf-8'

    def test_estimate_encoding_latin1(self):
        """Test encoding estimation for Latin-1."""
        # Latin-1 with special chars
        latin1_data = bytes([0x48, 0x65, 0x6c, 0x6c, 0x6f, 0xe9])  # "Helloé"
        encoding = estimate_clipboard_encoding(latin1_data)
        assert encoding in ('utf-8', 'latin-1')  # Could be either

    def test_estimate_encoding_ascii(self):
        """Test encoding estimation for ASCII."""
        ascii_data = b'Hello World'
        encoding = estimate_clipboard_encoding(ascii_data)
        assert encoding == 'utf-8'  # UTF-8 is superset of ASCII
