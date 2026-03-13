"""
Clipboard Synchronization Module

Implements VNC clipboard (ClientCutText/ServerCutText) extension support.
Allows synchronization of clipboard content between client and server.

Uses Python 3.13 features:
- Type parameter syntax
- Pattern matching for message handling
- Exception groups for error handling
"""

import struct
import time
from dataclasses import dataclass, field
from typing import Protocol, Self
from collections.abc import Callable
from enum import IntEnum


class ClipboardFormat(IntEnum):
    """Clipboard data formats supported by VNC protocol."""

    TEXT = 0  # Plain text (Latin-1)
    RTF = 1  # Rich Text Format
    HTML = 2  # HTML
    DIB = 3  # Device Independent Bitmap
    FILES = 4  # File list


@dataclass(slots=True)
class ClipboardData:
    """Represents clipboard data with format information."""

    format: ClipboardFormat
    content: bytes
    timestamp: float = field(default_factory=time.time)
    encoding: str = 'latin-1'

    @property
    def text(self) -> str:
        """Get clipboard content as text."""
        return self.content.decode(self.encoding, errors='replace')

    @classmethod
    def from_text(cls, text: str, encoding: str = 'latin-1') -> Self:
        """Create clipboard data from text string."""
        return cls(
            format=ClipboardFormat.TEXT,
            content=text.encode(encoding, errors='replace'),
            encoding=encoding
        )

    def to_vnc_message(self) -> bytes:
        """
        Convert to VNC ServerCutText message format.

        Format:
        - U8: message-type (3)
        - U8: padding
        - U16: padding
        - U32: length
        - U8 array: text
        """
        msg = bytearray()
        msg.append(3)  # ServerCutText message type
        msg.extend(b'\x00' * 3)  # Padding
        msg.extend(struct.pack('!I', len(self.content)))
        msg.extend(self.content)
        return bytes(msg)

    @classmethod
    def from_vnc_message(cls, data: bytes, encoding: str = 'latin-1') -> Self:
        """
        Parse VNC ClientCutText message.

        Format:
        - U8: message-type (6)
        - U8: padding
        - U16: padding
        - U32: length
        - U8 array: text
        """
        if len(data) < 8:
            raise ValueError("Clipboard message too short")

        msg_type = data[0]
        if msg_type != 6:
            raise ValueError(f"Invalid clipboard message type: {msg_type}")

        length = struct.unpack('!I', data[4:8])[0]
        content = data[8:8 + length]

        return cls(
            format=ClipboardFormat.TEXT,
            content=content,
            encoding=encoding
        )


class ClipboardManager:
    """
    Manages clipboard synchronization between VNC client and server.

    Features:
    - Bidirectional clipboard sync
    - Format conversion
    - Size limits for security
    - Change detection to avoid loops
    - Callback system for clipboard events
    """

    __slots__ = ('_server_content', '_client_content', '_max_size',
                 '_encoding', '_on_client_update', '_on_server_update',
                 '_last_sent_hash', '_enabled')

    def __init__(
        self,
        max_size: int = 1024 * 1024,  # 1MB default
        encoding: str = 'latin-1'
    ):
        self._server_content: ClipboardData | None = None
        self._client_content: ClipboardData | None = None
        self._max_size = max_size
        self._encoding = encoding
        self._on_client_update: list[Callable[[ClipboardData], None]] = []
        self._on_server_update: list[Callable[[ClipboardData], None]] = []
        self._last_sent_hash: int = 0
        self._enabled = True

    def enable(self) -> None:
        """Enable clipboard synchronization."""
        self._enabled = True

    def disable(self) -> None:
        """Disable clipboard synchronization."""
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Check if clipboard sync is enabled."""
        return self._enabled

    def handle_client_cut_text(self, message: bytes) -> None:
        """
        Handle ClientCutText message from VNC client.

        This is called when the client sends clipboard content to the server.
        """
        if not self._enabled:
            return

        try:
            clipboard_data = ClipboardData.from_vnc_message(message, self._encoding)

            # Check size limit
            if len(clipboard_data.content) > self._max_size:
                raise ValueError(
                    f"Clipboard content too large: {len(clipboard_data.content)} > {self._max_size}"
                )

            # Avoid loops - don't process if same as last sent
            content_hash = hash(clipboard_data.content)
            if content_hash == self._last_sent_hash:
                return

            self._client_content = clipboard_data

            # Notify listeners
            for callback in self._on_client_update:
                try:
                    callback(clipboard_data)
                except Exception as e:
                    # Don't let callback errors break clipboard handling
                    print(f"Clipboard callback error: {e}")

        except Exception as e:
            print(f"Error handling client clipboard: {e}")

    def set_server_clipboard(self, text: str) -> bytes | None:
        """
        Set server clipboard content and prepare message to send to client.

        Returns:
            VNC ServerCutText message bytes, or None if unchanged
        """
        if not self._enabled:
            return None

        try:
            clipboard_data = ClipboardData.from_text(text, self._encoding)

            # Check size limit
            if len(clipboard_data.content) > self._max_size:
                raise ValueError(
                    f"Clipboard content too large: {len(clipboard_data.content)} > {self._max_size}"
                )

            # Check if content actually changed
            if (self._server_content and
                self._server_content.content == clipboard_data.content):
                return None

            self._server_content = clipboard_data
            self._last_sent_hash = hash(clipboard_data.content)

            # Notify listeners
            for callback in self._on_server_update:
                try:
                    callback(clipboard_data)
                except Exception as e:
                    print(f"Clipboard callback error: {e}")

            return clipboard_data.to_vnc_message()

        except Exception as e:
            print(f"Error setting server clipboard: {e}")
            return None

    def get_client_clipboard_text(self) -> str | None:
        """Get the current client clipboard content as text."""
        if self._client_content:
            return self._client_content.text
        return None

    def get_server_clipboard_text(self) -> str | None:
        """Get the current server clipboard content as text."""
        if self._server_content:
            return self._server_content.text
        return None

    def on_client_update(self, callback: Callable[[ClipboardData], None]) -> None:
        """
        Register callback for client clipboard updates.

        The callback will be called whenever the client sends new clipboard content.
        """
        self._on_client_update.append(callback)

    def on_server_update(self, callback: Callable[[ClipboardData], None]) -> None:
        """
        Register callback for server clipboard updates.

        The callback will be called whenever the server clipboard is updated.
        """
        self._on_server_update.append(callback)

    def clear_callbacks(self) -> None:
        """Clear all registered callbacks."""
        self._on_client_update.clear()
        self._on_server_update.clear()

    def clear(self) -> None:
        """Clear all clipboard content."""
        self._server_content = None
        self._client_content = None
        self._last_sent_hash = 0

    def get_stats(self) -> dict[str, int | str | None]:
        """Get clipboard statistics."""
        return {
            'enabled': self._enabled,
            'max_size': self._max_size,
            'encoding': self._encoding,
            'client_content_size': len(self._client_content.content) if self._client_content else 0,
            'server_content_size': len(self._server_content.content) if self._server_content else 0,
            'client_timestamp': self._client_content.timestamp if self._client_content else None,
            'server_timestamp': self._server_content.timestamp if self._server_content else None,
            'callback_count': len(self._on_client_update) + len(self._on_server_update)
        }


class ClipboardHistory:
    """
    Maintains a history of clipboard changes for debugging and audit.

    Uses a circular buffer to limit memory usage.
    """

    __slots__ = ('_history', '_max_entries', '_current_index')

    def __init__(self, max_entries: int = 100):
        self._history: list[ClipboardData] = []
        self._max_entries = max_entries
        self._current_index = 0

    def add(self, clipboard_data: ClipboardData) -> None:
        """Add clipboard data to history."""
        if len(self._history) < self._max_entries:
            self._history.append(clipboard_data)
        else:
            # Circular buffer - overwrite oldest entry
            self._history[self._current_index] = clipboard_data
            self._current_index = (self._current_index + 1) % self._max_entries

    def get_recent(self, count: int = 10) -> list[ClipboardData]:
        """Get the most recent clipboard entries."""
        if count >= len(self._history):
            return self._history.copy()

        # Get last N entries in chronological order
        if len(self._history) < self._max_entries:
            return self._history[-count:]
        else:
            # Handle circular buffer
            start_idx = (self._current_index - count) % self._max_entries
            if start_idx < self._current_index:
                return self._history[start_idx:self._current_index]
            else:
                return (self._history[start_idx:] +
                       self._history[:self._current_index])

    def clear(self) -> None:
        """Clear all history."""
        self._history.clear()
        self._current_index = 0

    def get_stats(self) -> dict[str, int]:
        """Get history statistics."""
        total_size = sum(len(entry.content) for entry in self._history)
        return {
            'entry_count': len(self._history),
            'max_entries': self._max_entries,
            'total_size_bytes': total_size,
            'average_size_bytes': total_size // len(self._history) if self._history else 0
        }


# Utility functions for clipboard operations

def sanitize_clipboard_text(text: str, max_length: int = 1_000_000) -> str:
    """
    Sanitize clipboard text for security.

    - Limits length
    - Removes null bytes and control characters (except newlines/tabs)
    - Normalizes line endings
    """
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]

    # Remove problematic characters
    sanitized = []
    for char in text:
        code = ord(char)
        # Keep printable chars, newlines, tabs, carriage returns
        if (code >= 32 and code < 127) or char in '\n\r\t':
            sanitized.append(char)
        elif code >= 128:  # Keep non-ASCII if valid
            sanitized.append(char)

    result = ''.join(sanitized)

    # Normalize line endings to \n
    result = result.replace('\r\n', '\n').replace('\r', '\n')

    return result


def estimate_clipboard_encoding(data: bytes) -> str:
    """
    Estimate the best encoding for clipboard data.

    Tries to detect UTF-8, Latin-1, or other encodings.
    """
    # Try UTF-8 first (most common modern encoding)
    try:
        data.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass

    # Try Latin-1 (VNC default, never fails)
    try:
        data.decode('latin-1')
        return 'latin-1'
    except UnicodeDecodeError:
        pass

    # Fallback to ASCII with replacement
    return 'ascii'
