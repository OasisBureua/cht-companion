"""Per-user rate limiting — SCRUM-195 §8, backed by ElastiCache (Redis).

Confirmed live in dev: cht-dev-redis (replication group, cluster mode
disabled, no AUTH token, no TLS) at cht-dev-redis.nwaasy.ng.0001.use1
.cache.amazonaws.com:6379. Not yet wired into this app before this change.

Policy matches the doc's own stated default for ElastiCache-backed guardrails:
fail-open in dev (Redis down does not block chat), fail-closed in prod
(Redis down returns 503 rather than let quotas silently stop applying).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, TypeVar

import redis

from api import config

logger = logging.getLogger("cht-companion.ratelimit")

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

# Defaults chosen conservatively for a single-LLM-backed chat endpoint; not
# sourced from a numeric limit in the SCRUM-195 contract doc (none specified
# there) — override via env vars once real usage data suggests better values.
CHAT_REQUESTS_PER_MINUTE = int(os.environ.get("RATE_LIMIT_CHAT_PER_MINUTE", "20"))
CHAT_REQUESTS_PER_DAY = int(os.environ.get("RATE_LIMIT_CHAT_PER_DAY", "500"))

# /generate is service-to-service (cht-reports), not per-end-user, so it's
# keyed by caller rather than user_id and given a much lower ceiling. Report
# generation is a bulk/background job, not an interactive chat turn, and a
# runaway caller here would burn real Bedrock spend fast on the larger
# max_tokens ceiling /generate allows.
GENERATE_REQUESTS_PER_MINUTE = int(os.environ.get("RATE_LIMIT_GENERATE_PER_MINUTE", "5"))
GENERATE_REQUESTS_PER_DAY = int(os.environ.get("RATE_LIMIT_GENERATE_PER_DAY", "200"))

# CPR-21: organisation-wide cap on report generation, in Bedrock tokens
# (input + output) per UTC day, across every /generate caller. A run that
# starts under the cap finishes, so a day can end slightly over it.
GENERATE_TOKENS_PER_DAY = int(os.environ.get("RATE_LIMIT_GENERATE_TOKENS_PER_DAY", "500000"))

_MINUTE_WINDOW_SECONDS = 60
_DAY_WINDOW_SECONDS = 86400

_DEV_ENVIRONMENTS = {"development", "dev", "local"}

_T = TypeVar("_T")


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_ms: int) -> None:
        self.retry_after_ms = retry_after_ms
        super().__init__(f"rate limit exceeded, retry after {retry_after_ms}ms")


class TokenBudgetExceeded(RateLimitExceeded):
    """The day's /generate token budget (``limit`` tokens) is used up."""

    def __init__(self, retry_after_ms: int, limit: int) -> None:
        super().__init__(retry_after_ms)
        self.limit = limit


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


def _with_store(operation: Callable[["redis.Redis"], _T]) -> _T | None:
    """Run ``operation`` against the rate-limit store.

    Store unavailable (no REDIS_URL, or a RedisError/ValueError) is "the
    rate-limit store is broken," not "caller is over quota": returns None in
    dev (fail-open), raises ConnectionError in prod (fail-closed, 503 in the
    routers). RateLimitExceeded raised by ``operation`` passes through.
    """
    is_dev = config.CHT_ENVIRONMENT in _DEV_ENVIRONMENTS

    if not redis_configured():
        if is_dev:
            return None
        raise ConnectionError("REDIS_URL not configured")

    try:
        return operation(_client())
    except (redis.RedisError, ValueError) as exc:
        # RedisError: connection/timeout/auth failures at call time.
        # ValueError: a malformed REDIS_URL raised at _client() construction.
        if is_dev:
            return None
        raise ConnectionError(str(exc)) from exc


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

    def _check(client: "redis.Redis") -> None:
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

    _with_store(_check)


def check_generate_rate_limit(caller: str | None) -> None:
    """Raise RateLimitExceeded if the caller is over quota for /generate.

    Same fail-open(dev)/fail-closed(prod) policy as check_chat_rate_limit,
    keyed by caller (e.g. "cht-reports") rather than end-user_id since this
    is a service-to-service call.
    """
    bucket = caller or "unknown-caller"

    def _check(client: "redis.Redis") -> None:
        minute = _check_window(
            client, f"ratelimit:generate:{bucket}:minute:{int(time.time() // 60)}",
            GENERATE_REQUESTS_PER_MINUTE, _MINUTE_WINDOW_SECONDS,
        )
        if not minute.allowed:
            raise RateLimitExceeded(minute.retry_after_ms)

        day = _check_window(
            client, f"ratelimit:generate:{bucket}:day:{int(time.time() // 86400)}",
            GENERATE_REQUESTS_PER_DAY, _DAY_WINDOW_SECONDS,
        )
        if not day.allowed:
            raise RateLimitExceeded(day.retry_after_ms)

    _with_store(_check)


def _token_budget_key(now: float) -> str:
    return f"tokenbudget:generate:day:{int(now // _DAY_WINDOW_SECONDS)}"


def _ms_to_next_utc_day(now: float) -> int:
    return int((_DAY_WINDOW_SECONDS - now % _DAY_WINDOW_SECONDS) * 1000)


def check_generate_token_budget() -> None:
    """Raise TokenBudgetExceeded once today's /generate tokens reach the cap.

    Same fail-open(dev)/fail-closed(prod) policy as the request limits.
    """
    now = time.time()
    used = _with_store(lambda client: int(client.get(_token_budget_key(now)) or 0))
    if used is not None and used >= GENERATE_TOKENS_PER_DAY:
        raise TokenBudgetExceeded(_ms_to_next_utc_day(now), GENERATE_TOKENS_PER_DAY)


def record_generate_tokens(tokens: int) -> None:
    """Add a finished generation's tokens to today's total. Never raises:
    the tokens are spent either way, so a Redis error is only logged."""
    if tokens <= 0 or not redis_configured():
        return
    key = _token_budget_key(time.time())
    try:
        client = _client()
        total = client.incrby(key, tokens)
        if total == tokens:
            # Kept a day past its own so a late read still finds it.
            client.expire(key, 2 * _DAY_WINDOW_SECONDS)
    except (redis.RedisError, ValueError) as exc:
        logger.warning(
            "%s",
            json.dumps({"event": "generate_token_budget_record_failed", "tokens": tokens, "error": str(exc)}),
        )
