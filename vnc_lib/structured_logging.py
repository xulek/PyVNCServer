"""
Structured Logging Module

Enhanced logging with structured context, correlation IDs, and JSON output support.
Uses Python 3.13 features for better type safety and performance.

Uses Python 3.13 features:
- Type parameter syntax
- Pattern matching for log level handling
- Exception groups integration
"""

import logging
import json
import time
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Self
from dataclasses import dataclass, field, asdict
from collections.abc import Callable
from enum import StrEnum
from contextvars import ContextVar
from pathlib import Path


# Context variables for structured logging
_log_context: ContextVar[dict[str, Any]] = ContextVar('log_context', default={})
_correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')


class LogLevel(StrEnum):
    """Log levels matching Python logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class LogRecord:
    """Structured log record with context information."""

    timestamp: str
    level: str
    message: str
    logger_name: str
    thread_id: int
    correlation_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    exception: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Convert log record to JSON string."""
        return json.dumps(asdict(self), separators=(',', ':'))

    def to_human_readable(self) -> str:
        """Convert log record to human-readable string."""
        parts = [
            f"[{self.timestamp}]",
            f"[{self.level}]",
            f"[{self.logger_name}]"
        ]

        if self.correlation_id:
            parts.append(f"[{self.correlation_id}]")

        parts.append(self.message)

        # Add context if present
        if self.context:
            ctx_str = " | ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"| {ctx_str}")

        # Add extra fields if present
        if self.extra:
            extra_str = " | ".join(f"{k}={v}" for k, v in self.extra.items())
            parts.append(f"| {extra_str}")

        result = " ".join(parts)

        # Add exception if present
        if self.exception:
            result += f"\nException: {self.exception['type']}: {self.exception['message']}"
            if self.exception.get('traceback'):
                result += f"\n{self.exception['traceback']}"

        return result


class StructuredFormatter(logging.Formatter):
    """
    Logging formatter that outputs structured logs.

    Supports both JSON and human-readable formats.
    """

    def __init__(self, json_format: bool = False):
        super().__init__()
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured log."""
        # Get context from ContextVar
        context = _log_context.get({}).copy()
        correlation_id = _correlation_id.get('')

        # Create structured log record
        log_record = LogRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=record.levelname,
            message=record.getMessage(),
            logger_name=record.name,
            thread_id=threading.get_ident(),
            correlation_id=correlation_id,
            context=context
        )

        # Add exception info if present
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            log_record.exception = {
                'type': exc_type.__name__ if exc_type else 'Unknown',
                'message': str(exc_value),
                'traceback': ''.join(traceback.format_exception(
                    exc_type, exc_value, exc_traceback
                )) if exc_traceback else None
            }

        # Add extra fields from record
        extra = {}
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'message', 'pathname', 'process', 'processName',
                          'relativeCreated', 'thread', 'threadName', 'exc_info',
                          'exc_text', 'stack_info'):
                extra[key] = value

        if extra:
            log_record.extra = extra

        # Format as JSON or human-readable
        if self.json_format:
            return log_record.to_json()
        else:
            return log_record.to_human_readable()


class StructuredLogger:
    """
    Enhanced logger with structured logging support.

    Provides context management, correlation IDs, and performance tracking.
    """

    __slots__ = ('_logger', '_json_format')

    def __init__(self, name: str, json_format: bool = False):
        self._logger = logging.getLogger(name)
        self._json_format = json_format

        # Add structured formatter if not already configured
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(StructuredFormatter(json_format))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message with extra context."""
        self._logger.debug(message, extra=kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message with extra context."""
        self._logger.info(message, extra=kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with extra context."""
        self._logger.warning(message, extra=kwargs)

    def error(self, message: str, exc_info: bool = False, **kwargs: Any) -> None:
        """Log error message with extra context."""
        self._logger.error(message, exc_info=exc_info, extra=kwargs)

    def critical(self, message: str, exc_info: bool = False, **kwargs: Any) -> None:
        """Log critical message with extra context."""
        self._logger.critical(message, exc_info=exc_info, extra=kwargs)

    def set_level(self, level: LogLevel | str) -> None:
        """Set logging level."""
        if isinstance(level, LogLevel):
            level = level.value
        self._logger.setLevel(level)

    def add_context(self, **context: Any) -> None:
        """Add context to current context."""
        current_context = _log_context.get({}).copy()
        current_context.update(context)
        _log_context.set(current_context)

    def clear_context(self) -> None:
        """Clear logging context."""
        _log_context.set({})

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set correlation ID for log correlation."""
        _correlation_id.set(correlation_id)

    def clear_correlation_id(self) -> None:
        """Clear correlation ID."""
        _correlation_id.set('')

    def log_with_context(
        self,
        level: LogLevel,
        message: str,
        **context: Any
    ) -> None:
        """Log message with temporary context."""
        # Save current context
        old_context = _log_context.get({}).copy()

        try:
            # Add temporary context
            new_context = old_context.copy()
            new_context.update(context)
            _log_context.set(new_context)

            # Log message
            match level:
                case LogLevel.DEBUG:
                    self.debug(message)
                case LogLevel.INFO:
                    self.info(message)
                case LogLevel.WARNING:
                    self.warning(message)
                case LogLevel.ERROR:
                    self.error(message)
                case LogLevel.CRITICAL:
                    self.critical(message)

        finally:
            # Restore original context
            _log_context.set(old_context)


class LogContext:
    """
    Context manager for temporary logging context.

    Usage:
        with LogContext(user_id='123', request_id='abc'):
            logger.info('Processing request')
    """

    __slots__ = ('_context', '_old_context')

    def __init__(self, **context: Any):
        self._context = context
        self._old_context: dict[str, Any] = {}

    def __enter__(self) -> Self:
        """Enter context and save current context."""
        self._old_context = _log_context.get({}).copy()
        new_context = self._old_context.copy()
        new_context.update(self._context)
        _log_context.set(new_context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context and restore old context."""
        _log_context.set(self._old_context)
        return False


class CorrelationContext:
    """
    Context manager for correlation ID.

    Usage:
        with CorrelationContext('request-123'):
            logger.info('Processing')
    """

    __slots__ = ('_correlation_id', '_old_correlation_id')

    def __init__(self, correlation_id: str):
        self._correlation_id = correlation_id
        self._old_correlation_id: str = ''

    def __enter__(self) -> Self:
        """Enter context and set correlation ID."""
        self._old_correlation_id = _correlation_id.get('')
        _correlation_id.set(self._correlation_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context and restore old correlation ID."""
        _correlation_id.set(self._old_correlation_id)
        return False


class PerformanceLogger:
    """
    Context manager for logging performance metrics.

    Usage:
        with PerformanceLogger(logger, 'operation_name'):
            # Do work
            pass
    """

    __slots__ = ('_logger', '_operation', '_start_time', '_threshold')

    def __init__(
        self,
        logger: StructuredLogger,
        operation: str,
        threshold_seconds: float = 0.0
    ):
        self._logger = logger
        self._operation = operation
        self._start_time: float = 0.0
        self._threshold = threshold_seconds

    def __enter__(self) -> Self:
        """Start timing."""
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End timing and log performance."""
        duration = time.perf_counter() - self._start_time

        # Only log if above threshold
        if duration >= self._threshold:
            self._logger.info(
                f"Operation completed: {self._operation}",
                duration_seconds=round(duration, 6),
                operation=self._operation
            )

        return False


class AuditLogger:
    """
    Specialized logger for audit trails.

    Always logs in JSON format to a separate file for compliance.
    """

    __slots__ = ('_logger', '_file_path')

    def __init__(self, file_path: str | Path):
        self._file_path = Path(file_path)
        self._logger = logging.getLogger('audit')

        # Create file handler if not exists
        if not self._logger.handlers:
            # Create directory if needed
            self._file_path.parent.mkdir(parents=True, exist_ok=True)

            handler = logging.FileHandler(self._file_path)
            handler.setFormatter(StructuredFormatter(json_format=True))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False  # Don't propagate to root logger

    def log_event(
        self,
        event_type: str,
        user: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        result: str = "success",
        **extra: Any
    ) -> None:
        """Log an audit event."""
        audit_data = {
            'event_type': event_type,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'result': result
        }

        if user:
            audit_data['user'] = user
        if action:
            audit_data['action'] = action
        if resource:
            audit_data['resource'] = resource

        audit_data.update(extra)

        self._logger.info(
            f"Audit: {event_type}",
            extra=audit_data
        )

    def log_connection(
        self,
        client_ip: str,
        success: bool,
        user: str | None = None,
        **extra: Any
    ) -> None:
        """Log a connection attempt."""
        self.log_event(
            'connection',
            user=user,
            action='connect',
            resource=client_ip,
            result='success' if success else 'failure',
            **extra
        )

    def log_authentication(
        self,
        user: str,
        auth_type: str,
        success: bool,
        **extra: Any
    ) -> None:
        """Log an authentication attempt."""
        self.log_event(
            'authentication',
            user=user,
            action='authenticate',
            result='success' if success else 'failure',
            auth_type=auth_type,
            **extra
        )

    def log_access(
        self,
        user: str,
        resource: str,
        action: str,
        **extra: Any
    ) -> None:
        """Log resource access."""
        self.log_event(
            'access',
            user=user,
            action=action,
            resource=resource,
            **extra
        )


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    json_format: bool = False,
    log_file: str | Path | None = None
) -> None:
    """
    Configure global logging settings.

    Args:
        level: Logging level
        json_format: Use JSON format for logs
        log_file: Optional file to write logs to
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level.value if isinstance(level, LogLevel) else level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(StructuredFormatter(json_format))
    root_logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(StructuredFormatter(json_format=True))
        root_logger.addHandler(file_handler)


# Convenience function to create structured loggers
def get_logger(name: str, json_format: bool = False) -> StructuredLogger:
    """Create a structured logger with the given name."""
    return StructuredLogger(name, json_format)
