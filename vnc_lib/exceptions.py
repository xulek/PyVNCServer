"""
VNC Server Exception Definitions
Python 3.13 with Exception Groups (PEP 654)
"""

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


class ConnectionError(VNCError):
    """Connection-related errors"""
    pass


class ConfigurationError(VNCError):
    """Configuration errors"""
    pass


# Exception group utilities (Python 3.13)
class VNCExceptionGroup(ExceptionGroup):
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


class EncodingErrorGroup(VNCExceptionGroup):
    """Exception group for multiple encoding failures"""
    pass


# Exception handling utilities
def collect_exceptions(operations: list[tuple[str, callable]]) -> VNCExceptionGroup | None:
    """
    Execute multiple operations and collect exceptions

    Args:
        operations: List of (name, callable) tuples

    Returns:
        VNCExceptionGroup if any operations failed, None if all succeeded

    Example:
        >>> ops = [
        ...     ("encode_1", lambda: encoder1.encode(data)),
        ...     ("encode_2", lambda: encoder2.encode(data)),
        ... ]
        >>> errors = collect_exceptions(ops)
        >>> if errors:
        ...     handle_errors(errors)
    """
    exceptions: list[Exception] = []

    for name, operation in operations:
        try:
            operation()
        except Exception as e:
            # Annotate exception with operation name
            e.add_note(f"Failed during: {name}")
            exceptions.append(e)

    if exceptions:
        return VNCExceptionGroup.from_exceptions(
            f"Multiple operations failed: {len(exceptions)}/{len(operations)}",
            exceptions
        )

    return None


def handle_client_errors(client_errors: dict[str, Exception]) -> None:
    """
    Handle errors from multiple clients using exception groups

    Args:
        client_errors: Dict mapping client_id to exception

    Raises:
        MultiClientError: If any client errors occurred

    Example:
        >>> errors = {}
        >>> for client_id, client in clients.items():
        ...     try:
        ...         handle_client(client)
        ...     except Exception as e:
        ...         errors[client_id] = e
        >>> if errors:
        ...     handle_client_errors(errors)
    """
    if not client_errors:
        return

    # Annotate exceptions with client IDs
    exceptions = []
    for client_id, exc in client_errors.items():
        exc.add_note(f"Client: {client_id}")
        exceptions.append(exc)

    # Raise exception group
    raise MultiClientError(
        f"Errors from {len(client_errors)} client(s)",
        exceptions
    )


def categorize_exceptions(exc_group: ExceptionGroup) -> dict[str, list[Exception]]:
    """
    Categorize exceptions in a group by type

    Args:
        exc_group: Exception group to categorize

    Returns:
        Dict mapping exception type names to lists of exceptions

    Example:
        >>> try:
        ...     # Multiple operations
        ... except ExceptionGroup as eg:
        ...     categories = categorize_exceptions(eg)
        ...     if "ConnectionError" in categories:
        ...         log.error(f"Connection errors: {len(categories['ConnectionError'])}")
    """
    categories: dict[str, list[Exception]] = {}

    for exc in exc_group.exceptions:
        exc_type = type(exc).__name__
        if exc_type not in categories:
            categories[exc_type] = []
        categories[exc_type].append(exc)

    return categories


# Context manager for exception collection
class ExceptionCollector:
    """
    Context manager for collecting multiple exceptions

    Example:
        >>> with ExceptionCollector() as collector:
        ...     for item in items:
        ...         with collector.catch("process_item"):
        ...             process(item)
        >>> if collector.has_exceptions():
        ...     raise collector.create_exception_group("Processing failed")
    """

    def __init__(self):
        self.exceptions: list[Exception] = []
        self.current_operation: str | None = None

    def __enter__(self) -> 'ExceptionCollector':
        """Enter context"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - don't suppress exceptions"""
        return False

    def catch(self, operation_name: str):
        """
        Return a context manager that catches exceptions for a specific operation

        Usage:
            with collector.catch("operation_name"):
                do_something()
        """
        return _CatchContext(self, operation_name)

    def add_exception(self, exc: Exception, operation: str | None = None) -> None:
        """Add an exception to the collection"""
        if operation:
            exc.add_note(f"During: {operation}")
        self.exceptions.append(exc)

    def has_exceptions(self) -> bool:
        """Check if any exceptions were collected"""
        return bool(self.exceptions)

    def create_exception_group(self, message: str) -> VNCExceptionGroup | None:
        """Create exception group from collected exceptions"""
        if not self.exceptions:
            return None
        return VNCExceptionGroup.from_exceptions(message, self.exceptions)

    def raise_if_errors(self, message: str = "Multiple errors occurred") -> None:
        """Raise exception group if any exceptions were collected"""
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
            return True  # Suppress exception
        return False
