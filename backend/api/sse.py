"""SSE wire helpers — SCRUM-195 §4 (named events + stub-era shim)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from starlette.concurrency import run_in_threadpool

from api.bedrock import GenerationError, stream_generation
from api.rag import RagResult, find_sources
from api.retrieval import SourceContext, build_citation_url, build_snippet
from api.schemas import CitationEvent, DoneEvent, ErrorEvent, TokenEvent

logger = logging.getLogger("cht-companion.chat")


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


def _citation_from_source(source: SourceContext, citation_id: str) -> CitationEvent:
    """One citation per source. Snippet, timestamp and chunk_id come from the
    source's best-ranked chunk."""
    best = source.best
    return CitationEvent(
        citation_id=citation_id,
        source_id=source.source_id,
        chunk_id=best.chunk_id,
        source_type=source.source_type,
        title=source.title,
        url=build_citation_url(source.url, best.timestamp_start),
        playlist_url=source.playlist_url,
        snippet=build_snippet(best.text),
        timestamp=best.timestamp_start,
    )


def _build_context_block(sources: list[SourceContext]) -> str:
    """One labeled block per source: every retrieved passage from it, merged
    with neighbor chunks so an answer is not cut off at a chunk boundary."""
    return "\n\n".join(
        f"[c{i + 1}] ({source.title}):\n{source.context_text}" for i, source in enumerate(sources)
    )


async def retrieval_chat_stream(
    query: str,
    request_id: str,
    *,
    history: Sequence[dict] = (),
    shim: bool = True,
) -> AsyncIterator[str]:
    """Real retrieval + real Bedrock generation (SCRUM-196 §5.4, SCRUM-195 §4.2).

    Retrieval failure is non-terminal (retrieval_degraded, generation proceeds
    without context). Generation failure is terminal (llm_timeout, stream ends).
    """
    t0 = time.monotonic()
    sources: list[SourceContext] = []
    rag: RagResult | None = None
    retrieval_ms = 0

    try:
        # Embed, search and rerank all block on boto3/psycopg.
        rag = await run_in_threadpool(find_sources, query, list(history), request_id=request_id)
        sources = rag.sources
    except Exception as exc:
        # Non-terminal — generation still runs without citations. Embed failures
        # and DB/pgvector errors both map to retrieval_degraded so a bad
        # SET/query cannot crash the SSE stream (SCRUM-195 §4.4).
        logger.warning(
            "%s",
            json.dumps(
                {
                    "event": "chat_retrieval_degraded",
                    "request_id": request_id,
                    "error": str(exc),
                },
                separators=(",", ":"),
            ),
        )
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

    for i, source in enumerate(sources):
        yield emit_citation(_citation_from_source(source, citation_id=f"c{i + 1}"))

    context_block = _build_context_block(sources)
    logger.info(
        "%s",
        json.dumps(
            {
                "event": "chat_retrieval",
                "request_id": request_id,
                "citations": len(sources),
                "chunks": sum(len(s.hits) for s in sources),
                "candidates": rag.candidates if rag else 0,
                "reranked": rag.reranked if rag else False,
                "rewritten": bool(rag and rag.search_query != query),
                "top_distance": rag.top_distance if rag else None,
                "top_rerank_score": rag.top_rerank_score if rag else None,
                "history_turns": len(history),
                "retrieval_ms": retrieval_ms,
                "query_chars": len(query),
            },
            separators=(",", ":"),
        ),
    )

    index = 0
    first_token_ms = None
    finish_reason = "complete"
    generator = stream_generation(query, context_block, history=list(history), request_id=request_id)
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
        logger.warning(
            "%s",
            json.dumps(
                {
                    "event": "chat_generation_failed",
                    "request_id": request_id,
                    "error": str(exc),
                },
                separators=(",", ":"),
            ),
        )
        yield emit_error(
            ErrorEvent(
                code="llm_timeout",
                message="Generation failed or timed out.",
                retryable=True,
                retry_after_ms=None,
            )
        )

    total_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "%s",
        json.dumps(
            {
                "event": "chat_done",
                "request_id": request_id,
                "finish_reason": finish_reason,
                "citations_emitted": len(sources),
                "token_deltas": index,
                "latency_ms": {
                    "retrieval": retrieval_ms,
                    "first_token": first_token_ms or total_ms,
                    "total": total_ms,
                },
            },
            separators=(",", ":"),
        ),
    )
    for line in emit_done(
        DoneEvent(
            finish_reason=finish_reason,
            tokens_generated=index,
            citations_emitted=len(sources),
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
