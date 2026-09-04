"""SSE wire helpers — SCRUM-195 §4 (named events + stub-era shim)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from api.schemas import CitationEvent, DoneEvent, ErrorEvent, TokenEvent


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
