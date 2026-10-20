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

    def get(self, key: str) -> bytes | None:
        count = self._counts.get(key)
        return None if count is None else str(count).encode()

    def incrby(self, key: str, amount: int) -> int:
        self._counts[key] = self._counts.get(key, 0) + amount
        return self._counts[key]

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


def _token_budget(monkeypatch, fake: _FakeRedis, environment: str = "production"):
    from api import config, ratelimit

    monkeypatch.setattr(config, "CHT_ENVIRONMENT", environment)
    monkeypatch.setattr(ratelimit, "REDIS_URL", "redis://fake:6379/1")
    monkeypatch.setattr(ratelimit, "_client", lambda: fake)
    monkeypatch.setattr(ratelimit, "GENERATE_TOKENS_PER_DAY", 1000)
    return ratelimit


def test_token_budget_blocks_once_the_day_reaches_the_cap(monkeypatch) -> None:
    """CPR-21: organisation-wide daily token cap on /generate."""
    fake = _FakeRedis()
    ratelimit = _token_budget(monkeypatch, fake)

    ratelimit.record_generate_tokens(600)
    ratelimit.check_generate_token_budget()  # 600 of 1000: allowed

    ratelimit.record_generate_tokens(400)
    try:
        ratelimit.check_generate_token_budget()
    except ratelimit.TokenBudgetExceeded as exc:
        assert 0 < exc.retry_after_ms <= 86_400_000
        assert exc.limit == 1000
    else:
        raise AssertionError("expected TokenBudgetExceeded")


def test_token_budget_key_expires_once_and_holds_the_day_total(monkeypatch) -> None:
    fake = _FakeRedis()
    ratelimit = _token_budget(monkeypatch, fake)

    ratelimit.record_generate_tokens(10)
    (key,) = fake._counts
    first_expiry = fake._expires_at[key]
    time.sleep(0.01)
    ratelimit.record_generate_tokens(5)

    assert key.startswith("tokenbudget:generate:day:")
    assert fake._counts[key] == 15
    assert fake._expires_at[key] == first_expiry


def test_token_budget_store_errors(monkeypatch) -> None:
    """Unreachable Redis: dev lets the call through, prod refuses (503 in the
    router); recording never raises."""
    import redis as redis_lib

    class _Down(_FakeRedis):
        def get(self, key: str) -> bytes | None:
            raise redis_lib.ConnectionError("down")

        def incrby(self, key: str, amount: int) -> int:
            raise redis_lib.ConnectionError("down")

    ratelimit = _token_budget(monkeypatch, _Down(), environment="development")
    ratelimit.check_generate_token_budget()
    ratelimit.record_generate_tokens(10)

    ratelimit = _token_budget(monkeypatch, _Down(), environment="production")
    try:
        ratelimit.check_generate_token_budget()
    except ConnectionError:
        pass
    else:
        raise AssertionError("expected ConnectionError in production")


def test_generate_returns_429_when_the_token_budget_is_used_up(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from api import ratelimit
    from api.routers import generate as generate_router

    def _spent() -> None:
        raise ratelimit.TokenBudgetExceeded(retry_after_ms=3_600_000, limit=1234)

    counted: list[str | None] = []
    monkeypatch.setattr(generate_router, "check_generate_rate_limit", counted.append)
    monkeypatch.setattr(generate_router, "check_generate_token_budget", _spent)
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/generate", json={"system_prompt": "s", "user_content": "u"}, headers={"X-Client": "cht-reports"}
        )

    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "token_budget_exceeded"
    assert error["message"] == (
        "The daily report generation budget (1,234 tokens) is used up. It resets at 00:00 UTC."
    )
    assert error["retry_after_ms"] == 3_600_000
    assert response.headers.get("Retry-After") == "3600"
    # Refused for budget before the request counters ran.
    assert counted == []


def test_generate_request_limit_keeps_the_rate_limited_code(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from api import ratelimit
    from api.routers import generate as generate_router

    def _limited(_caller) -> None:
        raise ratelimit.RateLimitExceeded(retry_after_ms=5000)

    monkeypatch.setattr(generate_router, "check_generate_token_budget", lambda: None)
    monkeypatch.setattr(generate_router, "check_generate_rate_limit", _limited)
    from main import app

    with TestClient(app) as client:
        response = client.post("/generate", json={"system_prompt": "s", "user_content": "u"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_generate_records_the_tokens_it_used(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from api.routers import generate as generate_router

    recorded: list[int] = []
    monkeypatch.setattr(generate_router, "check_generate_rate_limit", lambda _caller: None)
    monkeypatch.setattr(generate_router, "check_generate_token_budget", lambda: None)
    monkeypatch.setattr(generate_router, "record_generate_tokens", recorded.append)
    monkeypatch.setattr(
        generate_router,
        "generate_completion",
        lambda *_args, **_kwargs: ("text", "complete", {"input_tokens": 12, "output_tokens": 34}),
    )
    from main import app

    with TestClient(app) as client:
        response = client.post("/generate", json={"system_prompt": "s", "user_content": "u"})

    assert response.status_code == 200
    assert recorded == [46]


def test_generate_records_zero_and_warns_when_usage_is_missing(monkeypatch) -> None:
    import json

    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from api.routers import generate as generate_router

    recorded: list[int] = []
    warnings: list[dict] = []
    monkeypatch.setattr(generate_router, "check_generate_rate_limit", lambda _caller: None)
    monkeypatch.setattr(generate_router, "check_generate_token_budget", lambda: None)
    monkeypatch.setattr(generate_router, "record_generate_tokens", recorded.append)
    monkeypatch.setattr(generate_router.logger, "warning", lambda _fmt, msg: warnings.append(json.loads(msg)))
    monkeypatch.setattr(
        generate_router,
        "generate_completion",
        lambda *_args, **_kwargs: ("text", "complete", {"input_tokens": None, "output_tokens": None}),
    )
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/generate", json={"system_prompt": "s", "user_content": "u"}, headers={"X-Request-Id": "r1"}
        )

    assert response.status_code == 200
    assert recorded == [0]
    assert warnings == [{"event": "generate_token_usage_missing", "request_id": "r1"}]
