"""Hybrid chunk retrieval over pgvector + Postgres full-text (SCRUM-196 §5.4).

Two candidate lists are fused by reciprocal rank:
  - vector: cosine distance to the query embedding (HNSW),
  - keyword: full-text match on title + text, so exact names like "DB-12"
    surface even when their embedding is not the closest.
Vector hits past RETRIEVAL_MAX_DISTANCE are dropped unless the keyword search
also found them. The caller reranks the fused list, then build_sources()
groups the survivors into one context block and one citation per source.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from db import connect

DEFAULT_K = 8
CANDIDATE_LIMIT = 30
HNSW_EF_SEARCH = 128
SIBLING_RADIUS = 1  # chunk_index N-1 and N+1 from the same source
RRF_K = 60
MAX_VECTOR_DISTANCE = float(os.environ.get("RETRIEVAL_MAX_DISTANCE", "0.8"))
_KEYWORD_TERMS = 16
_LIVE = "status NOT IN ('rejected', 'soft_deleted')"


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
    distance: float | None = None
    score: float = 0.0


@dataclass
class SourceContext:
    """Every retrieved chunk from one source, merged with its neighbors.

    `best` is the highest-ranked hit; the citation's snippet and timestamp
    come from it.
    """

    source_id: str
    source_type: str
    title: str
    url: str
    playlist_url: str | None
    best: RetrievedChunk
    hits: list[RetrievedChunk] = field(default_factory=list)
    context_text: str = ""


def keyword_query(text: str) -> str | None:
    """websearch_to_tsquery input that ORs the question's terms.

    Plain websearch syntax ANDs every word, so a natural question would need
    every term in one chunk. Leading hyphens are stripped because websearch
    reads them as NOT.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*", text):
        term = raw.strip(".-")
        # "DB12" and "DB-12" index differently; search both spellings.
        code = re.fullmatch(r"([A-Za-z]+)-?(\d+)", term)
        variants = [term, f"{code[1]}-{code[2]}", f"{code[1]}{code[2]}"] if code else [term]
        for variant in variants:
            key = variant.lower()
            if key in {"or", "and", "not"} or key in seen:
                continue
            seen.add(key)
            terms.append(variant)
        if len(terms) >= _KEYWORD_TERMS:
            break
    return " or ".join(terms[:_KEYWORD_TERMS]) or None


def _to_chunk(row: dict, *, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        source_type=row["source_type"],
        chunk_index=row["chunk_index"],
        title=row["title"],
        url=row["url"],
        playlist_url=row["playlist_url"],
        text=row["text"],
        timestamp_start=row["timestamp_start"],
        distance=row.get("distance"),
        score=score,
    )


def fuse(
    vector_rows: list[dict],
    keyword_rows: list[dict],
    *,
    limit: int = CANDIDATE_LIMIT,
    max_distance: float | None = MAX_VECTOR_DISTANCE,
) -> list[RetrievedChunk]:
    """Reciprocal rank fusion of the two candidate lists."""
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}

    for rank, row in enumerate(vector_rows):
        distance = row.get("distance")
        if max_distance is not None and distance is not None and distance > max_distance:
            continue
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (RRF_K + rank + 1)
        rows[row["chunk_id"]] = row

    for rank, row in enumerate(keyword_rows):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (RRF_K + rank + 1)
        rows.setdefault(row["chunk_id"], row)

    ordered = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)[:limit]
    return [_to_chunk(rows[chunk_id], score=scores[chunk_id]) for chunk_id in ordered]


_COLUMNS = (
    "chunk_id, source_id, source_type, chunk_index, title, url, playlist_url, text, timestamp_start"
)


def search(embedding: list[float], query_text: str = "", *, limit: int = CANDIDATE_LIMIT) -> list[RetrievedChunk]:
    """Fused vector + keyword candidates, best first. No neighbor text yet."""
    vector_literal = "[" + ",".join(str(x) for x in embedding) + "]"
    ts_query = keyword_query(query_text)

    with connect() as conn:
        # SET LOCAL cannot take bind parameters ($1) — interpolate a validated int.
        conn.execute(f"SET LOCAL hnsw.ef_search = {int(HNSW_EF_SEARCH)}")
        vector_rows = conn.execute(
            f"""
            SELECT {_COLUMNS}, embedding <=> %s::vector AS distance
            FROM chunks
            WHERE {_LIVE}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vector_literal, vector_literal, limit),
        ).fetchall()

        keyword_rows = []
        if ts_query:
            keyword_rows = conn.execute(
                f"""
                SELECT {_COLUMNS}, ts_rank_cd(text_search, q) AS keyword_score
                FROM chunks, websearch_to_tsquery('english', %s) AS q
                WHERE {_LIVE} AND text_search @@ q
                ORDER BY keyword_score DESC
                LIMIT %s
                """,
                (ts_query, limit),
            ).fetchall()

    return fuse(vector_rows, keyword_rows, limit=limit)


def _fetch_neighbors(conn, hits: list[RetrievedChunk]) -> dict[str, dict[int, str]]:
    """Text for every hit and its ±SIBLING_RADIUS neighbors, keyed by source then chunk_index."""
    if not hits:
        return {}

    conditions = []
    params: list[object] = []
    for hit in hits:
        conditions.append("(source_id = %s AND chunk_index BETWEEN %s AND %s)")
        params.extend([hit.source_id, hit.chunk_index - SIBLING_RADIUS, hit.chunk_index + SIBLING_RADIUS])

    rows = conn.execute(
        f"""
        SELECT source_id, chunk_index, text
        FROM chunks
        WHERE {_LIVE} AND ({' OR '.join(conditions)})
        ORDER BY source_id, chunk_index
        """,
        params,
    ).fetchall()

    by_source: dict[str, dict[int, str]] = {}
    for row in rows:
        by_source.setdefault(row["source_id"], {})[row["chunk_index"]] = row["text"]
    return by_source


def _merge_windows(hits: list[RetrievedChunk], texts: dict[int, str]) -> str:
    """One passage per run of consecutive chunk indices, so overlapping
    neighbor windows from two hits in the same source are not repeated."""
    wanted: set[int] = set()
    for hit in hits:
        wanted.update(range(hit.chunk_index - SIBLING_RADIUS, hit.chunk_index + SIBLING_RADIUS + 1))
        texts.setdefault(hit.chunk_index, hit.text)

    passages: list[list[str]] = []
    previous: int | None = None
    for index in sorted(i for i in wanted if i in texts):
        if previous is None or index != previous + 1:
            passages.append([])
        passages[-1].append(texts[index])
        previous = index
    return "\n\n…\n\n".join(" ".join(passage) for passage in passages)


def group_by_source(hits: list[RetrievedChunk], neighbors: dict[str, dict[int, str]]) -> list[SourceContext]:
    """Group ranked hits by source, keeping the order of each source's best hit."""
    grouped: dict[str, SourceContext] = {}
    for hit in hits:
        source = grouped.get(hit.source_id)
        if source is None:
            source = SourceContext(
                source_id=hit.source_id,
                source_type=hit.source_type,
                title=hit.title,
                url=hit.url,
                playlist_url=hit.playlist_url,
                best=hit,
            )
            grouped[hit.source_id] = source
        source.hits.append(hit)

    for source in grouped.values():
        source.context_text = _merge_windows(source.hits, dict(neighbors.get(source.source_id, {})))
    return list(grouped.values())


def build_sources(hits: list[RetrievedChunk]) -> list[SourceContext]:
    if not hits:
        return []
    with connect() as conn:
        neighbors = _fetch_neighbors(conn, hits)
    return group_by_source(hits, neighbors)


def retrieve(embedding: list[float], query_text: str = "", *, k: int = DEFAULT_K) -> list[SourceContext]:
    """search() + build_sources() without reranking."""
    return build_sources(search(embedding, query_text)[:k])


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
