"""Titan embeddings client for the ingest Lambda (CHAT-21).

Mirrors backend/api/bedrock.py's embed_query exactly (same model, same 1024
dims, same normalize=True) so vectors written here are comparable to query-time
embeddings in backend/api/retrieval.py. Duplicated rather than imported: kb/
and backend/ are separate deploy units (Lambda vs Fargate) with independent
requirements.txt, per the repo's existing split.
"""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache

import boto3

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBEDDING_MODEL = os.environ.get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBED_DIM = 1024


class EmbeddingError(Exception):
    pass


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def embed_text(text: str) -> list[float]:
    """Embed one chunk of text. Raises EmbeddingError on any Bedrock failure."""
    try:
        response = _client().invoke_model(
            modelId=EMBEDDING_MODEL,
            body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
    except Exception as exc:  # noqa: BLE001 — any boto3/network failure collapses here
        raise EmbeddingError(str(exc)) from exc

    embedding = payload.get("embedding")
    if not isinstance(embedding, list) or len(embedding) != EMBED_DIM:
        raise EmbeddingError(
            f"unexpected embedding shape: {type(embedding)} "
            f"len={len(embedding) if isinstance(embedding, list) else 'n/a'}"
        )
    return embedding


def embed_texts(texts: list[str], *, retry: int = 2, backoff_s: float = 1.0) -> list[list[float]]:
    """Embed a batch sequentially (Titan has no native batch API). Retries
    each item on failure since throttling is the common transient case.
    """
    out: list[list[float]] = []
    for text in texts:
        last_err: Exception | None = None
        for attempt in range(retry + 1):
            try:
                out.append(embed_text(text))
                last_err = None
                break
            except EmbeddingError as exc:
                last_err = exc
                if attempt < retry:
                    time.sleep(backoff_s * (attempt + 1))
        if last_err is not None:
            raise last_err
    return out
