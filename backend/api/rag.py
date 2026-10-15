"""Question to ranked sources: rewrite a follow-up, hybrid search, rerank, group.

Rewrite and rerank failures degrade quietly (raw question, fused order).
Embedding and database failures raise, and the chat stream reports
retrieval_degraded.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from api.bedrock import RerankError, RewriteError, embed_query, rerank, rewrite_query
from api.retrieval import RetrievedChunk, SourceContext, build_sources, search

RERANK_TOP_N = int(os.environ.get("RERANK_TOP_N", "8"))
RERANK_MIN_SCORE = float(os.environ.get("RERANK_MIN_SCORE", "0.1"))
_RERANK_DOC_CHARS = 2000


@dataclass
class RagResult:
    sources: list[SourceContext]
    search_query: str
    candidates: int
    reranked: bool
    top_distance: float | None
    top_rerank_score: float | None


def _rerank(
    query: str, candidates: list[RetrievedChunk], request_id: str
) -> tuple[list[RetrievedChunk], bool, float | None]:
    if not candidates:
        return [], False, None

    documents = [f"{c.title}\n{c.text}"[:_RERANK_DOC_CHARS] for c in candidates]
    try:
        ranked = rerank(query, documents, top_n=RERANK_TOP_N, request_id=request_id)
    except RerankError:
        return candidates[:RERANK_TOP_N], False, None

    kept: list[RetrievedChunk] = []
    for index, score in ranked:
        if score < RERANK_MIN_SCORE or not 0 <= index < len(candidates):
            continue
        candidate = candidates[index]
        candidate.score = score
        kept.append(candidate)
    return kept, True, ranked[0][1] if ranked else None


def find_sources(query: str, history: Sequence[dict], *, request_id: str) -> RagResult:
    search_query = query
    if history:
        try:
            search_query = rewrite_query(query, history, request_id=request_id)
        except RewriteError:
            search_query = query

    candidates = search(embed_query(search_query), search_query)
    top, reranked, top_score = _rerank(search_query, candidates, request_id)
    distances = [c.distance for c in candidates if c.distance is not None]

    return RagResult(
        sources=build_sources(top),
        search_query=search_query,
        candidates=len(candidates),
        reranked=reranked,
        top_distance=min(distances) if distances else None,
        top_rerank_score=top_score,
    )
