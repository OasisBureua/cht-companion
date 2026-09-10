"""Bedrock client helpers — Titan embeddings + Claude generation (SCRUM-195 §4, SCRUM-196 §3, §5.4)."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from functools import lru_cache

import boto3

from db import EMBED_DIM, EMBEDDING_MODEL

logger = logging.getLogger("cht-companion.bedrock")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# Prefer BEDROCK_CHAT_MODEL_ID (.env.example / ECS); keep GENERATION_MODEL as alias.
GENERATION_MODEL = os.environ.get(
    "BEDROCK_CHAT_MODEL_ID",
    os.environ.get(
        "BEDROCK_GENERATION_MODEL",
        "us.anthropic.claude-sonnet-5",
    ),
)


class EmbeddingError(Exception):
    """Raised when Bedrock embedding fails — caller maps this to retrieval_failed/degraded."""


class GenerationError(Exception):
    """Raised when Bedrock generation fails — caller maps this to llm_timeout/llm_refused/internal."""


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _log_bedrock(event: str, **fields: object) -> None:
    """One-line JSON ops log — never includes prompt/response text."""
    payload = {"event": event, "region": AWS_REGION, **fields}
    logger.info("%s", json.dumps(payload, separators=(",", ":"), default=str))


def embed_query(text: str) -> list[float]:
    """Embed a query string via Titan Text Embeddings v2 (SCRUM-196 §3.2, 1024 dims).

    Raises EmbeddingError on any Bedrock failure (throttling, auth, timeout) —
    callers decide whether that's retrieval_failed (terminal) or a fallback.
    """
    t0 = time.monotonic()
    try:
        response = _client().invoke_model(
            modelId=EMBEDDING_MODEL,
            body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
    except Exception as exc:  # noqa: BLE001 — any boto3/network failure collapses here
        _log_bedrock(
            "bedrock_embed_error",
            model_id=EMBEDDING_MODEL,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
        raise EmbeddingError(str(exc)) from exc

    embedding = payload.get("embedding")
    if not isinstance(embedding, list) or len(embedding) != EMBED_DIM:
        err = (
            f"unexpected embedding shape from Bedrock: {type(embedding)} "
            f"len={len(embedding) if isinstance(embedding, list) else 'n/a'}"
        )
        _log_bedrock(
            "bedrock_embed_error",
            model_id=EMBEDDING_MODEL,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=err,
        )
        raise EmbeddingError(err)

    _log_bedrock(
        "bedrock_embed_ok",
        model_id=EMBEDDING_MODEL,
        dimensions=len(embedding),
        input_chars=len(text),
        latency_ms=int((time.monotonic() - t0) * 1000),
    )
    return embedding


SYSTEM_PROMPT = (
    "You are CHT Companion, a medical Q&A assistant for Community Health Technologies. "
    "Answer the user's question using ONLY the provided context chunks. Each chunk is "
    "labeled with a citation id like [c1], [c2]. Cite the chunks you used inline with "
    "their id, e.g. \"...as shown in [c1].\" If the context does not contain enough "
    "information to answer, say so plainly rather than guessing."
)


def _build_generation_messages(query: str, context_block: str) -> list[dict]:
    user_content = query.strip()
    if context_block:
        user_content = f"Context:\n{context_block}\n\nQuestion: {query.strip()}"
    return [{"role": "user", "content": user_content}]


# Bedrock's messageStop.stopReason values, mapped onto our API contract's
# narrower FinishReason enum (complete | truncated | error | cancelled).
_STOP_REASON_MAP = {
    "end_turn": "complete",
    "stop_sequence": "complete",
    "max_tokens": "truncated",
    "content_filtered": "error",
    "guardrail_intervened": "error",
    "tool_use": "complete",
}


def stream_generation(
    query: str,
    context_block: str,
    *,
    max_tokens: int = 1024,
    temperature: float | None = None,
    request_id: str | None = None,
) -> Iterator[str]:
    """Stream Claude's response text via Bedrock's converse_stream API.

    Yields text deltas as they arrive. On completion, the generator's return
    value (accessible via StopIteration.value when driven manually, e.g.
    `value = yield from stream_generation(...)`) is the FinishReason mapped
    from Bedrock's messageStop.stopReason — see retrieval_chat_stream for
    the consumption pattern.

    Raises GenerationError on any Bedrock failure (throttling, auth, timeout,
    malformed response) — caller maps this to llm_timeout/llm_refused/internal
    per SCRUM-195 §4.4.

    Claude Sonnet 5 rejects `temperature` (deprecated for this model). Omit it
    unless the caller explicitly opts in for models that still accept it.
    """
    inference_config: dict = {"maxTokens": max_tokens}
    if temperature is not None:
        inference_config["temperature"] = temperature

    t0 = time.monotonic()
    try:
        response = _client().converse_stream(
            modelId=GENERATION_MODEL,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {"role": m["role"], "content": [{"text": m["content"]}]}
                for m in _build_generation_messages(query, context_block)
            ],
            inferenceConfig=inference_config,
        )
    except Exception as exc:  # noqa: BLE001 — any boto3/network failure collapses here
        _log_bedrock(
            "bedrock_generate_error",
            model_id=GENERATION_MODEL,
            request_id=request_id,
            has_context=bool(context_block),
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
        raise GenerationError(str(exc)) from exc

    stop_reason = "complete"
    bedrock_stop: str | None = None
    usage: dict = {}
    bedrock_latency_ms: int | None = None
    deltas = 0
    try:
        for event in response["stream"]:
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            text = delta.get("text")
            if text:
                deltas += 1
                yield text
            message_stop = event.get("messageStop")
            if message_stop:
                bedrock_stop = message_stop.get("stopReason")
                stop_reason = _STOP_REASON_MAP.get(bedrock_stop, "complete")
            metadata = event.get("metadata") or {}
            if metadata.get("usage"):
                usage = metadata["usage"]
            if metadata.get("metrics", {}).get("latencyMs") is not None:
                bedrock_latency_ms = int(metadata["metrics"]["latencyMs"])
    except Exception as exc:  # noqa: BLE001 — mid-stream failure (throttle, disconnect)
        _log_bedrock(
            "bedrock_generate_error",
            model_id=GENERATION_MODEL,
            request_id=request_id,
            has_context=bool(context_block),
            deltas=deltas,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
        raise GenerationError(str(exc)) from exc

    _log_bedrock(
        "bedrock_generate_ok",
        model_id=GENERATION_MODEL,
        request_id=request_id,
        has_context=bool(context_block),
        finish_reason=stop_reason,
        bedrock_stop_reason=bedrock_stop,
        deltas=deltas,
        input_tokens=usage.get("inputTokens"),
        output_tokens=usage.get("outputTokens"),
        total_tokens=usage.get("totalTokens"),
        bedrock_latency_ms=bedrock_latency_ms,
        wall_latency_ms=int((time.monotonic() - t0) * 1000),
    )
    return stop_reason
