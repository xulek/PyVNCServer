"""Connection security guards used before and during VNC authentication."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True, slots=True)
class AuthDecision:
    allowed: bool
    retry_after: float = 0.0


class AuthRateLimiter:
    """Sliding-window per-IP authentication failure limiter.

    Successful authentication clears the failure history for the source IP.
    Failures trigger a bounded exponential delay and eventually a temporary
    refusal until failures leave the configured time window.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: float = 30.0,
        max_backoff_seconds: float = 2.0,
    ) -> None:
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(0.1, float(window_seconds))
        self.max_backoff_seconds = max(0.0, float(max_backoff_seconds))
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, ip: str, now: float) -> deque[float]:
        failures = self._failures[ip]
        cutoff = now - self.window_seconds
        while failures and failures[0] < cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(ip, None)
            return deque()
        return failures

    def check(self, ip: str) -> AuthDecision:
        now = time.monotonic()
        with self._lock:
            failures = self._prune(ip, now)
            if len(failures) < self.max_failures:
                return AuthDecision(True, 0.0)
            retry_after = max(0.0, failures[0] + self.window_seconds - now)
            return AuthDecision(False, retry_after)

    def record_failure(self, ip: str) -> float:
        now = time.monotonic()
        with self._lock:
            failures = self._prune(ip, now)
            failures.append(now)
            self._failures[ip] = failures
            exponent = max(0, len(failures) - 1)
            delay = min(self.max_backoff_seconds, 0.125 * (2 ** exponent))
            return delay

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


class PerIPConnectionLimiter:
    """Thread-safe concurrent connection cap per source IP."""

    def __init__(self, max_connections_per_ip: int = 4) -> None:
        self.max_connections_per_ip = max(1, int(max_connections_per_ip))
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, ip: str) -> bool:
        with self._lock:
            current = self._counts.get(ip, 0)
            if current >= self.max_connections_per_ip:
                return False
            self._counts[ip] = current + 1
            return True

    def release(self, ip: str) -> None:
        with self._lock:
            current = self._counts.get(ip, 0)
            if current <= 1:
                self._counts.pop(ip, None)
            else:
                self._counts[ip] = current - 1

    def get_count(self, ip: str) -> int:
        with self._lock:
            return self._counts.get(ip, 0)
