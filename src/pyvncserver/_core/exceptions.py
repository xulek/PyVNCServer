"""
VNC Server Exception Definitions
Python 3.13 with Exception Groups (PEP 654)
"""

import builtins
import sys
from typing import Sequence


# Base exceptions
class VNCError(Exception):
    """Base exception for all VNC-related errors"""
    pass


class ProtocolError(VNCError):
    """Protocol-related errors (version negotiation, message parsing)"""
    pass


class AuthenticationError(VNCError):
    """Authentication failures"""
    pass


class EncodingError(VNCError):
    """Encoding/decoding errors"""
    pass


class ScreenCaptureError(VNCError):
    """Screen capture failures"""
    pass


class ConnectionError(VNCError, builtins.ConnectionError):
    """Connection-related errors"""
    pass


class ConfigurationError(VNCError):
    """Configuration errors"""
    pass


# Exception group utilities (Python 3.11+)
if sys.version_info >= (3, 11):
    _BaseExceptionGroup = ExceptionGroup
else:
    class _BaseExceptionGroup(BaseException):
        """Minimal ExceptionGroup polyfill for Python < 3.11."""

        def __init__(self, message: str, exceptions: Sequence[Exception]):
            super().__init__(message, exceptions)
            self._message = message
            self._exceptions = list(exceptions)

        @property
        def message(self) -> str:
            return self._message

        @property
        def exceptions(self) -> list[Exception]:
            return self._exceptions

        def __str__(self) -> str:
            return self._message

        def __repr__(self) -> str:
            return f"{type(self).__name__}({self._message!r}, {self._exceptions!r})"


class VNCExceptionGroup(_BaseExceptionGroup):
    """Custom exception group for VNC operations"""

    @classmethod
    def from_exceptions(cls, message: str, exceptions: Sequence[Exception]) -> 'VNCExceptionGroup':
        """Create exception group from list of exceptions"""
        if not exceptions:
            raise ValueError("Cannot create exception group without exceptions")
        return cls(message, exceptions)

    def filter_by_type(self, exc_type: type[Exception]) -> list[Exception]:
        """Filter exceptions by type"""
        return [e for e in self.exceptions if isinstance(e, exc_type)]

    def has_type(self, exc_type: type[Exception]) -> bool:
        """Check if group contains exception of given type"""
        return any(isinstance(e, exc_type) for e in self.exceptions)


class MultiClientError(VNCExceptionGroup):
    """Exception group for multi-client operations"""
    pass


def categorize_exceptions(exc_group: _BaseExceptionGroup) -> dict[str, list[Exception]]:
    """Categorize exceptions in a group by type"""
    categories: dict[str, list[Exception]] = {}

    for exc in exc_group.exceptions:
        exc_type = type(exc).__name__
        if exc_type not in categories:
            categories[exc_type] = []
        categories[exc_type].append(exc)

    return categories


# Context manager for exception collection
class ExceptionCollector:
    """Context manager for collecting multiple exceptions"""

    def __init__(self):
        self.exceptions: list[Exception] = []
        self.current_operation: str | None = None

    def __enter__(self) -> 'ExceptionCollector':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def catch(self, operation_name: str):
        return _CatchContext(self, operation_name)

    def add_exception(self, exc: Exception, operation: str | None = None) -> None:
        if operation:
            note = f"During: {operation}"
            if hasattr(exc, 'add_note'):
                exc.add_note(note)
            else:
                existing = getattr(exc, '__notes__', None)
                if existing is not None:
                    existing.append(note)
                else:
                    exc.__notes__ = [note]
        self.exceptions.append(exc)

    def has_exceptions(self) -> bool:
        return bool(self.exceptions)

    def create_exception_group(self, message: str) -> VNCExceptionGroup | None:
        if not self.exceptions:
            return None
        return VNCExceptionGroup.from_exceptions(message, self.exceptions)

    def raise_if_errors(self, message: str = "Multiple errors occurred") -> None:
        if self.exceptions:
            raise self.create_exception_group(message)


class _CatchContext:
    """Internal context manager for catching exceptions"""

    def __init__(self, collector: ExceptionCollector, operation: str):
        self.collector = collector
        self.operation = operation

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            self.collector.add_exception(exc_val, self.operation)
        return True
        return False
