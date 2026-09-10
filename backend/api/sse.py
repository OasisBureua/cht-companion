"""SSE wire helpers — SCRUM-195 §4 (named events + stub-era shim)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from api.bedrock import GenerationError, embed_query, stream_generation
from api.retrieval import RetrievedChunk, build_citation_url, build_snippet, retrieve
from api.schemas import CitationEvent, DoneEvent, ErrorEvent, TokenEvent

logger = logging.getLogger(__name__)


def sse_event(name: str, payload: dict[str, Any]) -> str:
    """Named SSE event: event: <name>\\ndata: <json>\\n\\n"""
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def sse_comment(text: str = "keepalive") -> str:
    return f":{text}\n\n"


def emit_token(event: TokenEvent, *, shim: bool = True) -> list[str]:
    """v1 named token + optional unnamed stub-era data line (§10.1)."""
    lines = [sse_event("token", event.model_dump())]
    if shim:
        lines.append(f"data: {json.dumps({'text': event.text}, separators=(',', ':'))}\n\n")
    return lines


def emit_citation(event: CitationEvent) -> str:
    return sse_event("citation", event.model_dump())


def emit_error(event: ErrorEvent) -> str:
    data = event.model_dump(exclude_none=True)
    return sse_event("error", data)


def emit_done(event: DoneEvent, *, shim: bool = True) -> list[str]:
    lines = [sse_event("done", event.model_dump())]
    if shim:
        lines.append("data: [DONE]\n\n")
    return lines


def _citation_from_chunk(chunk: RetrievedChunk, citation_id: str) -> CitationEvent:
    return CitationEvent(
        citation_id=citation_id,
        source_id=chunk.source_id,
        chunk_id=chunk.chunk_id,
        source_type=chunk.source_type,
        title=chunk.title,
        url=build_citation_url(chunk.url, chunk.timestamp_start),
        playlist_url=chunk.playlist_url,
        snippet=build_snippet(chunk.text),
        timestamp=chunk.timestamp_start,
    )


def _build_context_block(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks):
        parts.append(f"[c{i + 1}] ({chunk.title}): {chunk.text}")
    return "\n\n".join(parts)


async def retrieval_chat_stream(
    query: str,
    request_id: str,
    *,
    shim: bool = True,
) -> AsyncIterator[str]:
    """Real retrieval + real Bedrock generation (SCRUM-196 §5.4, SCRUM-195 §4.2).

    Retrieval failure is non-terminal (retrieval_degraded, generation proceeds
    without context). Generation failure is terminal (llm_timeout, stream ends).
    """
    t0 = time.monotonic()
    chunks: list[RetrievedChunk] = []
    retrieval_ms = 0

    try:
        embedding = embed_query(query)
        chunks = retrieve(embedding)
    except Exception as exc:
        # Non-terminal — generation still runs without citations. Embed failures
        # and DB/pgvector errors both map to retrieval_degraded so a bad
        # SET/query cannot crash the SSE stream (SCRUM-195 §4.4).
        logger.warning("retrieval degraded: %s", exc)
        yield emit_error(
            ErrorEvent(
                code="retrieval_degraded",
                message="Retrieval unavailable; answering without knowledge-base context.",
                retryable=True,
                retry_after_ms=None,
            )
        )
    finally:
        retrieval_ms = int((time.monotonic() - t0) * 1000)

    for i, chunk in enumerate(chunks):
        yield emit_citation(_citation_from_chunk(chunk, citation_id=f"c{i + 1}"))

    context_block = _build_context_block(chunks)

    index = 0
    first_token_ms = None
    finish_reason = "complete"
    generator = stream_generation(query, context_block)
    try:
        while True:
            try:
                delta = next(generator)
            except StopIteration as stop:
                # Normal exhaustion — stop.value is stream_generation's mapped
                # FinishReason (from Bedrock messageStop.stopReason), or None
                # if the generator ended without one (shouldn't happen, but
                # don't crash on it).
                finish_reason = stop.value or "complete"
                break
            if first_token_ms is None:
                first_token_ms = int((time.monotonic() - t0) * 1000)
            for line in emit_token(TokenEvent(text=delta, index=index), shim=shim):
                yield line
            index += 1
    except GenerationError as exc:
        finish_reason = "error"
        logger.warning("generation failed: %s", exc)
        yield emit_error(
            ErrorEvent(
                code="llm_timeout",
                message="Generation failed or timed out.",
                retryable=True,
                retry_after_ms=None,
            )
        )

    total_ms = int((time.monotonic() - t0) * 1000)
    for line in emit_done(
        DoneEvent(
            finish_reason=finish_reason,
            tokens_generated=index,
            citations_emitted=len(chunks),
            latency_ms={
                "retrieval": retrieval_ms,
                "first_token": first_token_ms or total_ms,
                "total": total_ms,
            },
            request_id=request_id,
        ),
        shim=shim,
    ):
        yield line


async def placeholder_chat_stream(
    query: str,
    request_id: str,
    *,
    shim: bool = True,
) -> AsyncIterator[str]:
    """Placeholder RAG stream until Bedrock + pgvector retrieval is wired."""
    yield emit_citation(
        CitationEvent(
            citation_id="c1",
            source_id="curated:hello-world",
            chunk_id="curated:hello-world:chunk:0",
            source_type="curated_doc",
            title="Hello World",
            url="https://communityhealth.media/",
            playlist_url=None,
            snippet="Placeholder citation until retrieval is implemented.",
            timestamp=None,
        )
    )

    text = (
        "CHT Companion received your question but retrieval and Bedrock are not "
        f"wired yet. You asked: {query.strip()}"
    )
    index = 0
    for word in text.split(" "):
        piece = f"{word} "
        for line in emit_token(TokenEvent(text=piece, index=index), shim=shim):
            yield line
        index += 1

    for line in emit_done(
        DoneEvent(
            finish_reason="complete",
            tokens_generated=index,
            citations_emitted=1,
            latency_ms={"retrieval": 0, "first_token": 0, "total": 0},
            request_id=request_id,
        ),
        shim=shim,
    ):
        yield line
