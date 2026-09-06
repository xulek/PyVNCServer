"""Tests for pre-authentication abuse protection helpers."""

from pyvncserver.runtime.security import AuthRateLimiter, PerIPConnectionLimiter


def test_per_ip_connection_limiter_enforces_and_releases_capacity():
    limiter = PerIPConnectionLimiter(max_connections_per_ip=2)

    assert limiter.acquire("192.0.2.1") is True
    assert limiter.acquire("192.0.2.1") is True
    assert limiter.acquire("192.0.2.1") is False
    assert limiter.acquire("192.0.2.2") is True

    limiter.release("192.0.2.1")
    assert limiter.acquire("192.0.2.1") is True


def test_auth_rate_limiter_blocks_after_configured_failure_count():
    limiter = AuthRateLimiter(max_failures=3, window_seconds=30.0, max_backoff_seconds=0.0)
    ip = "192.0.2.10"

    assert limiter.check(ip).allowed is True
    limiter.record_failure(ip)
    limiter.record_failure(ip)
    assert limiter.check(ip).allowed is True
    limiter.record_failure(ip)

    decision = limiter.check(ip)
    assert decision.allowed is False
    assert decision.retry_after >= 0.0


def test_auth_rate_limiter_success_clears_failures():
    limiter = AuthRateLimiter(max_failures=2, window_seconds=30.0, max_backoff_seconds=0.0)
    ip = "192.0.2.20"
    limiter.record_failure(ip)
    limiter.record_failure(ip)
    assert limiter.check(ip).allowed is False

    limiter.record_success(ip)
    assert limiter.check(ip).allowed is True
