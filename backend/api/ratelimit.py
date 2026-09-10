"""Per-user rate limiting — SCRUM-195 §8, backed by ElastiCache (Redis).

Confirmed live in dev: cht-dev-redis (replication group, cluster mode
disabled, no AUTH token, no TLS) at cht-dev-redis.nwaasy.ng.0001.use1
.cache.amazonaws.com:6379. Not yet wired into this app before this change.

Policy matches the doc's own stated default for ElastiCache-backed guardrails:
fail-open in dev (Redis down does not block chat), fail-closed in prod
(Redis down returns 503 rather than let quotas silently stop applying).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache

import redis

from api import config

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

# Defaults chosen conservatively for a single-LLM-backed chat endpoint; not
# sourced from a numeric limit in the SCRUM-195 contract doc (none specified
# there) — override via env vars once real usage data suggests better values.
CHAT_REQUESTS_PER_MINUTE = int(os.environ.get("RATE_LIMIT_CHAT_PER_MINUTE", "20"))
CHAT_REQUESTS_PER_DAY = int(os.environ.get("RATE_LIMIT_CHAT_PER_DAY", "500"))

_MINUTE_WINDOW_SECONDS = 60
_DAY_WINDOW_SECONDS = 86400


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_ms: int) -> None:
        self.retry_after_ms = retry_after_ms
        super().__init__(f"rate limit exceeded, retry after {retry_after_ms}ms")


@dataclass
class _WindowResult:
    allowed: bool
    retry_after_ms: int


def redis_configured() -> bool:
    return bool(REDIS_URL)


@lru_cache(maxsize=1)
def _client() -> "redis.Redis":
    return redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)


def _check_window(client: "redis.Redis", key: str, limit: int, window_seconds: int) -> _WindowResult:
    """Fixed-window counter via INCR + EXPIRE NX (atomic enough for a soft
    per-user quota — a fixed window can slightly over-admit at window
    boundaries, which is an acceptable tradeoff for this use case over the
    complexity of a sliding-window Lua script).
    """
    count = client.incr(key)
    if count == 1:
        client.expire(key, window_seconds)
    if count <= limit:
        return _WindowResult(allowed=True, retry_after_ms=0)
    ttl_ms = max(client.pttl(key), 0)
    return _WindowResult(allowed=False, retry_after_ms=ttl_ms)


def check_chat_rate_limit(user_id: str | None) -> None:
    """Raise RateLimitExceeded if the caller is over quota.

    No-op (allowed) when Redis is not configured and CHT_ENVIRONMENT is dev —
    fail-open, per SCRUM-195's dependency-failure-matrix policy. In prod,
    an unreachable Redis raises RateLimitExceeded-adjacent behavior is NOT
    used here; the caller (chat.py) is expected to treat a raised
    ConnectionError as a 503, matching "fail-closed in prod" for the
    rate-limit *store*, not the same thing as being *rate limited*.
    """
    bucket = user_id or "anonymous"
    is_dev = config.CHT_ENVIRONMENT in {"development", "dev", "local"}

    if not redis_configured():
        if is_dev:
            return
        raise ConnectionError("REDIS_URL not configured")

    try:
        client = _client()
        minute = _check_window(
            client, f"ratelimit:chat:{bucket}:minute:{int(time.time() // 60)}",
            CHAT_REQUESTS_PER_MINUTE, _MINUTE_WINDOW_SECONDS,
        )
        if not minute.allowed:
            raise RateLimitExceeded(minute.retry_after_ms)

        day = _check_window(
            client, f"ratelimit:chat:{bucket}:day:{int(time.time() // 86400)}",
            CHAT_REQUESTS_PER_DAY, _DAY_WINDOW_SECONDS,
        )
        if not day.allowed:
            raise RateLimitExceeded(day.retry_after_ms)
    except RateLimitExceeded:
        raise
    except (redis.RedisError, ValueError) as exc:
        # RedisError: connection/timeout/auth failures at call time.
        # ValueError: a malformed REDIS_URL raised at _client() construction.
        # Both are "the rate-limit store is broken," not "caller is over
        # quota" — same fail-open(dev)/fail-closed(prod) policy applies.
        if is_dev:
            return
        raise ConnectionError(str(exc)) from exc
