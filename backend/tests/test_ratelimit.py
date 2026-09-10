import time

from fastapi.testclient import TestClient


class _FakeRedis:
    """Minimal in-memory stand-in for the redis.Redis calls _check_window
    makes (incr/expire/pttl) — avoids adding a mocking-library dependency
    for a handful of calls, matching this repo's existing plain-monkeypatch
    test style.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._expires_at: dict[str, float] = {}

    def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self._expires_at[key] = time.time() + seconds

    def pttl(self, key: str) -> int:
        expires_at = self._expires_at.get(key)
        if expires_at is None:
            return -1
        return max(int((expires_at - time.time()) * 1000), 0)


def test_rate_limit_fail_open_in_dev_without_redis(monkeypatch) -> None:
    """No REDIS_URL + dev environment: chat still works, no 429/503."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CHT_ENVIRONMENT", "development")
    from api import config

    config.refresh_from_env()
    from main import app

    with TestClient(app) as client:
        response = client.post("/chat", json={"query": "hello"})
        assert response.status_code == 200


def test_rate_limit_fail_closed_in_prod_without_redis(monkeypatch) -> None:
    """No REDIS_URL + prod environment: rate-limit store unreachable -> 503."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CHT_ENVIRONMENT", "production")
    from api import config

    config.refresh_from_env()
    from main import app

    with TestClient(app) as client:
        response = client.post("/chat", json={"query": "hello"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "internal"

    monkeypatch.setenv("CHT_ENVIRONMENT", "development")
    config.refresh_from_env()


def test_rate_limit_returns_429_with_retry_after(monkeypatch) -> None:
    """Simulated over-quota caller gets a 429 with the rate_limited envelope
    and a Retry-After header, before any SSE streaming begins.
    """
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from api import ratelimit
    from api.routers import chat as chat_router

    def _always_limited(_user_id):
        raise ratelimit.RateLimitExceeded(retry_after_ms=5000)

    monkeypatch.setattr(chat_router, "check_chat_rate_limit", _always_limited)
    from main import app

    with TestClient(app) as client:
        response = client.post("/chat", json={"query": "hello"})
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"
        assert response.json()["error"]["retry_after_ms"] == 5000
        assert response.headers.get("Retry-After") == "5"


def test_check_window_allows_up_to_limit_then_blocks() -> None:
    """Direct test of the fixed-window boundary math (count <= limit), not
    monkeypatched away — regression coverage for the off-by-one the limit
    check could get wrong (e.g. count < limit vs count <= limit).
    """
    from api import ratelimit

    client = _FakeRedis()
    key = "ratelimit:test:minute:0"

    for _ in range(3):
        result = ratelimit._check_window(client, key, limit=3, window_seconds=60)
        assert result.allowed is True

    blocked = ratelimit._check_window(client, key, limit=3, window_seconds=60)
    assert blocked.allowed is False
    assert blocked.retry_after_ms > 0


def test_check_window_sets_expire_only_on_first_increment() -> None:
    """Regression: EXPIRE must only be set when count == 1 — setting it on
    every call would keep resetting the window's TTL and the window would
    never actually roll over as long as requests kept arriving.
    """
    from api import ratelimit

    client = _FakeRedis()
    key = "ratelimit:test:minute:0"

    ratelimit._check_window(client, key, limit=100, window_seconds=60)
    first_expiry = client._expires_at[key]

    time.sleep(0.01)
    ratelimit._check_window(client, key, limit=100, window_seconds=60)
    second_expiry = client._expires_at[key]

    assert first_expiry == second_expiry
