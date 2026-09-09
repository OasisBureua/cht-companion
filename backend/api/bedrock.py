"""Bedrock client helpers — Titan embeddings for retrieval (SCRUM-196 §3, §5.4)."""

from __future__ import annotations

import json
import os
from functools import lru_cache

import boto3

from db import EMBED_DIM, EMBEDDING_MODEL

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class EmbeddingError(Exception):
    """Raised when Bedrock embedding fails — caller maps this to retrieval_failed/degraded."""


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def embed_query(text: str) -> list[float]:
    """Embed a query string via Titan Text Embeddings v2 (SCRUM-196 §3.2, 1024 dims).

    Raises EmbeddingError on any Bedrock failure (throttling, auth, timeout) —
    callers decide whether that's retrieval_failed (terminal) or a fallback.
    """
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
            f"unexpected embedding shape from Bedrock: {type(embedding)} "
            f"len={len(embedding) if isinstance(embedding, list) else 'n/a'}"
        )
    return embedding
