"""Chunk retrieval — pure vector k-NN over pgvector (SCRUM-196 §5.4)."""

from __future__ import annotations

from dataclasses import dataclass, field

from db import connect

DEFAULT_K = 10
HNSW_EF_SEARCH = 128
SIBLING_RADIUS = 1  # chunk_index N-1 and N+1 from the same source


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_type: str
    chunk_index: int
    title: str
    url: str
    playlist_url: str | None
    text: str
    timestamp_start: int | None
    # Immediate same-source neighbor text (chunk_index ±SIBLING_RADIUS), ordered
    # by chunk_index. Extends the LLM's context past a single chunk's boundary
    # without adding separate citations — the citation still points at this
    # chunk specifically, not its siblings.
    context_text: str = field(default="")


def _fetch_siblings(
    conn, hits: list[dict]
) -> dict[tuple[str, int], str]:
    """One query for every hit's neighbor range, keyed by (source_id, chunk_index)."""
    if not hits:
        return {}

    conditions = []
    params: list[object] = []
    for hit in hits:
        conditions.append("(source_id = %s AND chunk_index BETWEEN %s AND %s)")
        params.extend(
            [hit["source_id"], hit["chunk_index"] - SIBLING_RADIUS, hit["chunk_index"] + SIBLING_RADIUS]
        )

    rows = conn.execute(
        f"""
        SELECT source_id, chunk_index, text
        FROM chunks
        WHERE status = 'approved' AND ({' OR '.join(conditions)})
        ORDER BY source_id, chunk_index
        """,
        params,
    ).fetchall()

    by_source: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        by_source.setdefault(row["source_id"], []).append((row["chunk_index"], row["text"]))

    context: dict[tuple[str, int], str] = {}
    for hit in hits:
        source_rows = by_source.get(hit["source_id"], [])
        window = [
            text
            for idx, text in source_rows
            if hit["chunk_index"] - SIBLING_RADIUS <= idx <= hit["chunk_index"] + SIBLING_RADIUS
        ]
        context[(hit["source_id"], hit["chunk_index"])] = " ".join(window) if window else hit["text"]

    return context


def retrieve(embedding: list[float], *, k: int = DEFAULT_K) -> list[RetrievedChunk]:
    """Top-k approved chunks by cosine distance to the query embedding, each
    extended with its immediate same-source neighbors' text.

    Mirrors SCRUM-196 §5.4's pure vector k-NN query: status='approved' filter,
    HNSW ef_search tuned per-query, embedding <=> distance ordering. The
    sibling-chunk join is a second, cheap indexed query (chunks_source_id_idx),
    not a second vector search — it exists because a fixed-size chunk boundary
    can land mid-thought (confirmed by a manual quality test against real
    ingested data: a real chunk cut off before the source finished explaining a
    trial's results, and the model correctly said so rather than guessing, but
    the answer was incomplete because the next chunk was never fetched).
    """
    vector_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    with connect() as conn:
        # SET LOCAL cannot take bind parameters ($1) — interpolate a validated int.
        conn.execute(f"SET LOCAL hnsw.ef_search = {int(HNSW_EF_SEARCH)}")
        rows = conn.execute(
            """
            SELECT chunk_id, source_id, source_type, chunk_index, title, url,
                   playlist_url, text, timestamp_start
            FROM chunks
            WHERE status = 'approved'
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vector_literal, k),
        ).fetchall()

        sibling_context = _fetch_siblings(conn, rows)

    return [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            source_type=row["source_type"],
            chunk_index=row["chunk_index"],
            title=row["title"],
            url=row["url"],
            playlist_url=row["playlist_url"],
            text=row["text"],
            timestamp_start=row["timestamp_start"],
            context_text=sibling_context.get((row["source_id"], row["chunk_index"]), row["text"]),
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
