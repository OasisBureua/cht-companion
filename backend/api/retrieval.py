"""Chunk retrieval — pure vector k-NN over pgvector (SCRUM-196 §5.4)."""

from __future__ import annotations

from dataclasses import dataclass

from db import connect

DEFAULT_K = 10
HNSW_EF_SEARCH = 128


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_type: str
    title: str
    url: str
    playlist_url: str | None
    text: str
    timestamp_start: int | None


def retrieve(embedding: list[float], *, k: int = DEFAULT_K) -> list[RetrievedChunk]:
    """Top-k approved chunks by cosine distance to the query embedding.

    Mirrors SCRUM-196 §5.4's pure vector k-NN query: status='approved' filter,
    HNSW ef_search tuned per-query, embedding <=> distance ordering.
    """
    vector_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    with connect() as conn:
        conn.execute("SET LOCAL hnsw.ef_search = %s", (HNSW_EF_SEARCH,))
        rows = conn.execute(
            """
            SELECT chunk_id, source_id, source_type, title, url, playlist_url,
                   text, timestamp_start
            FROM chunks
            WHERE status = 'approved'
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vector_literal, k),
        ).fetchall()

    return [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            source_type=row["source_type"],
            title=row["title"],
            url=row["url"],
            playlist_url=row["playlist_url"],
            text=row["text"],
            timestamp_start=row["timestamp_start"],
        )
        for row in rows
    ]


def build_citation_url(url: str, timestamp_start: int | None) -> str:
    """SCRUM-195 §4.3: append ?t=<seconds> when a temporal timestamp is present."""
    if timestamp_start is None:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}t={timestamp_start}"


def build_snippet(text: str, max_chars: int = 200) -> str:
    """SCRUM-195 §4.3: ~200 char snippet, the exact chunk text the LLM saw."""
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rsplit(" ", 1)[0] + "…"
