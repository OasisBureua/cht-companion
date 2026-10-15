"""Bedrock client helpers — Titan embeddings + Claude generation (SCRUM-195 §4, SCRUM-196 §3, §5.4)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Iterator, Sequence
from functools import lru_cache

import boto3
from botocore.config import Config

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
# Follow-up rewrite is a short call; point it at a smaller model to cut latency.
REWRITE_MODEL = os.environ.get("BEDROCK_REWRITE_MODEL_ID", "").strip() or GENERATION_MODEL
# Empty disables reranking; retrieval then keeps its fused order.
RERANK_MODEL = os.environ.get("BEDROCK_RERANK_MODEL_ID", "cohere.rerank-v3-5:0").strip()


class EmbeddingError(Exception):
    """Raised when Bedrock embedding fails — caller maps this to retrieval_failed/degraded."""


class GenerationError(Exception):
    """Raised when Bedrock generation fails — caller maps this to llm_timeout/llm_refused/internal."""


class RerankError(Exception):
    """Reranking failed or is disabled. Callers fall back to retrieval order."""


class RewriteError(Exception):
    """Follow-up rewrite failed. Callers search with the raw question."""


# A full report (up to 8192 output tokens) takes minutes; botocore's default
# 60s read timeout would cut it off. Stay under the caller's 300s wait
# (Node fetch headers timeout in cht-reports) so a slow call fails here
# with a clean 502 instead of a dropped connection.
_BEDROCK_CONFIG = Config(
    read_timeout=int(os.environ.get("BEDROCK_READ_TIMEOUT_SECONDS", "270")),
    connect_timeout=10,
    retries={"max_attempts": 2, "mode": "standard"},
)


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION, config=_BEDROCK_CONFIG)


@lru_cache(maxsize=1)
def _agent_client():
    return boto3.client("bedrock-agent-runtime", region_name=AWS_REGION, config=_BEDROCK_CONFIG)


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


def rerank(
    query: str,
    documents: Sequence[str],
    *,
    top_n: int,
    request_id: str | None = None,
) -> list[tuple[int, float]]:
    """Score documents against the query with the Bedrock Rerank API.

    Returns (document index, relevance score in 0..1), best first.
    Raises RerankError when disabled or on any Bedrock failure.
    """
    if not RERANK_MODEL:
        raise RerankError("reranking disabled")
    if not documents:
        return []

    t0 = time.monotonic()
    try:
        response = _agent_client().rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": query}}],
            sources=[
                {"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": doc}}}
                for doc in documents
            ],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "numberOfResults": min(top_n, len(documents)),
                    "modelConfiguration": {
                        "modelArn": f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{RERANK_MODEL}",
                    },
                },
            },
        )
        results = [(int(r["index"]), float(r["relevanceScore"])) for r in response.get("results", [])]
    except Exception as exc:  # noqa: BLE001 — any boto3/network/shape failure collapses here
        _log_bedrock(
            "bedrock_rerank_error",
            model_id=RERANK_MODEL,
            request_id=request_id,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
        raise RerankError(str(exc)) from exc

    _log_bedrock(
        "bedrock_rerank_ok",
        model_id=RERANK_MODEL,
        request_id=request_id,
        documents=len(documents),
        results=len(results),
        top_score=results[0][1] if results else None,
        latency_ms=int((time.monotonic() - t0) * 1000),
    )
    return sorted(results, key=lambda r: r[1], reverse=True)


REWRITE_PROMPT = (
    "You turn the latest message in a conversation into one standalone search query "
    "for a medical knowledge base. Resolve pronouns and references using the earlier "
    "turns, keep drug, trial and doctor names exactly as written, and return only the "
    "query text with no quotes or explanation."
)
_REWRITE_TURNS = 6
_REWRITE_TURN_CHARS = 1500


def rewrite_query(query: str, history: Sequence[dict], *, request_id: str | None = None) -> str:
    """Rewrite a follow-up like "what about brain mets?" into a standalone query.

    Raises RewriteError on any failure or an empty rewrite.
    """
    transcript = "\n".join(
        f"{turn['role']}: {_strip_citation_markers(turn['content'])[:_REWRITE_TURN_CHARS]}"
        for turn in list(history)[-_REWRITE_TURNS:]
    )
    user_content = f"Conversation:\n{transcript}\n\nLatest message: {query.strip()}"

    t0 = time.monotonic()
    try:
        response = _client().converse(
            modelId=REWRITE_MODEL,
            system=[{"text": REWRITE_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_content}]}],
            inferenceConfig={"maxTokens": 200},
        )
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        rewritten = "".join(block.get("text", "") for block in blocks).strip().strip('"')
    except Exception as exc:  # noqa: BLE001 — any boto3/network failure collapses here
        _log_bedrock(
            "bedrock_rewrite_error",
            model_id=REWRITE_MODEL,
            request_id=request_id,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
        raise RewriteError(str(exc)) from exc

    if not rewritten:
        raise RewriteError("empty rewrite")

    _log_bedrock(
        "bedrock_rewrite_ok",
        model_id=REWRITE_MODEL,
        request_id=request_id,
        history_turns=len(history),
        latency_ms=int((time.monotonic() - t0) * 1000),
    )
    return rewritten[:4000]


SYSTEM_PROMPT = (
    "You are CHT Companion, the assistant for Community Health Media (CHM) and the CHT "
    "Platform. You answer questions about CHM, the platform, and the medical content in "
    "its knowledge base. Answer using ONLY the provided context. Each source in the "
    "context is labeled with a citation id like [c1], [c2]. Cite the sources you used "
    "inline with their id, e.g. \"...as shown in [c1].\" Cite only the sources that "
    "directly support a statement, at most three per statement, and never list sources "
    "just because they repeat the same text. Earlier messages are the "
    "conversation so far: use them to understand follow-up questions, but take facts "
    "only from the context. If no context is provided, or it does not answer the "
    "question, say plainly that the CHT knowledge base does not cover it rather than "
    "guessing."
)

_CITATION_MARKER = re.compile(r"\s?\[[cC]\d+\]")


def _strip_citation_markers(text: str) -> str:
    """Old answers cite ids from an earlier retrieval; drop them so they don't
    get confused with the ids in the current context."""
    return _CITATION_MARKER.sub("", text)


def _build_generation_messages(
    query: str,
    context_block: str,
    history: Sequence[dict] | None = None,
) -> list[dict]:
    """Earlier turns, then the question with its context. Bedrock converse needs
    alternating roles starting with user, so empty turns are dropped, a leading
    assistant turn is dropped, and same-role neighbors are merged."""
    if context_block:
        final = f"Context:\n{context_block}\n\nQuestion: {query.strip()}"
    else:
        final = f"No knowledge-base context matched this question.\n\nQuestion: {query.strip()}"

    turns: list[dict] = []
    for turn in history or []:
        content = turn["content"].strip()
        if turn["role"] == "assistant":
            content = _strip_citation_markers(content).strip()
        if content:
            turns.append({"role": turn["role"], "content": content})
    turns.append({"role": "user", "content": final})

    merged: list[dict] = []
    for turn in turns:
        if not merged and turn["role"] != "user":
            continue
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["content"] = f"{merged[-1]['content']}\n\n{turn['content']}"
        else:
            merged.append(dict(turn))
    return merged


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


def generate_completion(
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int = 4096,
    temperature: float | None = None,
    request_id: str | None = None,
) -> tuple[str, str, dict[str, int | None]]:
    """Non-streaming Bedrock generation for callers that need a plain
    "prompt in, completion out" call with no retrieval step, for example
    cht-reports' report-generation pipeline, which assembles its own input
    packet (transcript + survey data) and doesn't want this service's RAG
    chat context.

    Unlike stream_generation, this takes an arbitrary system_prompt rather
    than the hardcoded chat SYSTEM_PROMPT, and returns the complete text
    plus finish reason in one call rather than yielding deltas. A report
    is a complete document, not an incremental chat response.

    Raises GenerationError on any Bedrock failure, same as stream_generation.
    Returns (text, finish_reason, usage) with usage = {input_tokens, output_tokens}.
    """
    inference_config: dict = {"maxTokens": max_tokens}
    if temperature is not None:
        inference_config["temperature"] = temperature

    t0 = time.monotonic()
    try:
        response = _client().converse(
            modelId=GENERATION_MODEL,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_content}]}],
            inferenceConfig=inference_config,
        )
    except Exception as exc:  # noqa: BLE001 — any boto3/network failure collapses here
        _log_bedrock(
            "bedrock_generate_completion_error",
            model_id=GENERATION_MODEL,
            request_id=request_id,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
        raise GenerationError(str(exc)) from exc

    bedrock_stop = response.get("stopReason")
    stop_reason = _STOP_REASON_MAP.get(bedrock_stop, "complete")
    usage = response.get("usage", {})

    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(block.get("text", "") for block in content_blocks)
    reasoning_blocks = sum(1 for block in content_blocks if "reasoningContent" in block)

    _log_bedrock(
        "bedrock_generate_completion_ok",
        model_id=GENERATION_MODEL,
        request_id=request_id,
        finish_reason=stop_reason,
        bedrock_stop_reason=bedrock_stop,
        input_tokens=usage.get("inputTokens"),
        output_tokens=usage.get("outputTokens"),
        total_tokens=usage.get("totalTokens"),
        text_chars=len(text),
        reasoning_blocks=reasoning_blocks,
        wall_latency_ms=int((time.monotonic() - t0) * 1000),
    )

    return text, stop_reason, {
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
    }


def stream_generation(
    query: str,
    context_block: str,
    *,
    history: Sequence[dict] | None = None,
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
                for m in _build_generation_messages(query, context_block, history)
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
