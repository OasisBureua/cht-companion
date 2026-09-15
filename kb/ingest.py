"""Orchestrates one source through chunk -> embed -> upsert (CHAT-20 + CHAT-21).

Source-agnostic: callers hand it plain text + a SourceInput, so the same
path serves the bootstrap transcript set today and a live catalog/YouTube
caption puller later (CHAT-19's EventBridge/SQS trigger calls this per
source once that wiring exists — not built yet, tracked separately).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from chunking import chunk_text
from embedding import EMBEDDING_MODEL, EmbeddingError, embed_texts
from store import ChunkInput, SourceInput, UpsertResult, connect, upsert_chunks, upsert_source

logger = logging.getLogger("cht-companion-kb.ingest")


@dataclass
class IngestResult:
    source_id: str
    chunks_total: int
    chunks_written: int
    chunks_skipped: int
    error: str | None = None


def ingest_source(source: SourceInput, text: str) -> IngestResult:
    """Chunk `text`, embed each chunk, upsert source + chunks in one transaction.

    Idempotent: re-running with identical text writes nothing (content-hash
    skip in upsert_chunks). A partial failure (e.g. Bedrock throttled mid-batch)
    raises before any DB write, so a retry starts clean rather than leaving a
    half-ingested source.
    """
    pieces = chunk_text(text)
    if not pieces:
        return IngestResult(source.source_id, chunks_total=0, chunks_written=0, chunks_skipped=0)

    try:
        embeddings = embed_texts([p.text for p in pieces])
    except EmbeddingError as exc:
        logger.error("embedding_failed", extra={"source_id": source.source_id, "error": str(exc)})
        return IngestResult(
            source.source_id, chunks_total=len(pieces), chunks_written=0, chunks_skipped=0, error=str(exc)
        )

    chunk_inputs = [
        ChunkInput(index=piece.index, text=piece.text, embedding=embedding)
        for piece, embedding in zip(pieces, embeddings, strict=True)
    ]

    with connect() as conn:
        with conn.transaction():
            upsert_source(conn, source)
            result: UpsertResult = upsert_chunks(conn, source, chunk_inputs)

    logger.info(
        "ingest_ok",
        extra={
            "source_id": source.source_id,
            "chunks_total": len(pieces),
            "written": result.written,
            "skipped": result.skipped,
        },
    )
    return IngestResult(
        source.source_id,
        chunks_total=len(pieces),
        chunks_written=result.written,
        chunks_skipped=result.skipped,
    )


def make_source_id(source_type: str, external_id: str) -> str:
    """Deterministic source_id, e.g. 'youtube_caption:eJ1wTcuL27U'. Stable across
    re-ingests, unlike the legacy chmbot's random-suffixed ids (inventory §8.5).
    """
    return f"{source_type}:{external_id}"
