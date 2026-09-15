"""Idempotent source + chunk upsert against the SCRUM-196 KB schema (CHAT-21).

Mirrors backend/db's connect() pattern (psycopg v3, dict rows) and
backend/api/admin_store.py's query style so ingest-written rows and
admin/retrieval-read rows agree on shape. New sources land status='pending'
(schema default) — nothing here ever writes 'approved'; that's CHAT-34's
admin review surface, by design (CHT-9 requires human approval before a
chunk is retrievable, since retrieval.py only reads status='approved').
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import boto3
import psycopg
from psycopg.rows import dict_row

EMBED_DIM = 1024

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


@lru_cache(maxsize=1)
def _secretsmanager_client():
    return boto3.client("secretsmanager", region_name=AWS_REGION)


@lru_cache(maxsize=1)
def _database_url_from_secret(secret_arn: str) -> str:
    """Resolve DATABASE_URL from Secrets Manager at cold start and cache it
    for the life of the Lambda execution environment.

    ECS gets DATABASE_URL injected directly via the task definition's
    `secrets` block (valueFrom = "<arn>:url::", see
    infrastructure/terraform/modules/compute/ecs-companion/main.tf) — that
    JSON-key extraction syntax has no Lambda equivalent, so kb/ (unlike
    backend/) fetches and parses the secret itself. The secret's JSON shape
    (username/password/host/port/dbname/url) is defined in
    infrastructure/terraform/modules/database/companion-db/main.tf.
    """
    response = _secretsmanager_client().get_secret_value(SecretId=secret_arn)
    payload = json.loads(response["SecretString"])
    url = payload.get("url", "").strip()
    if not url:
        raise RuntimeError(f"secret {secret_arn} has no 'url' field")
    return url


def database_url() -> str:
    """DATABASE_URL directly if set (local dev, tests), else resolved from
    DATABASE_SECRET_ARN (Lambda's actual env — see kb/.env.example and the
    live cht-dev-companion-kb function config).
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url

    secret_arn = os.environ.get("DATABASE_SECRET_ARN", "").strip()
    if secret_arn:
        return _database_url_from_secret(secret_arn)

    raise RuntimeError("neither DATABASE_URL nor DATABASE_SECRET_ARN is set")


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), row_factory=dict_row)


@dataclass
class SourceInput:
    source_id: str
    source_type: str  # 'youtube_caption' | 'catalog_clip' | 'curated_doc'
    title: str
    url: str
    embedding_model: str
    playlist_url: str | None = None
    external_id: str | None = None
    doctors: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    content_date: date | None = None


@dataclass
class ChunkInput:
    index: int
    text: str
    embedding: list[float]
    timestamp_start: int | None = None
    timestamp_end: int | None = None
    duration_seconds: int | None = None
    speaker: str | None = None
    speakers_in_chunk: list[str] = field(default_factory=list)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vector_literal(embedding: list[float]) -> str:
    if len(embedding) != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM}-dim embedding, got {len(embedding)}")
    return "[" + ",".join(str(x) for x in embedding) + "]"


def upsert_source(conn: psycopg.Connection, source: SourceInput) -> None:
    """Insert the source row if new; leave status/approval fields untouched on
    conflict so a re-ingest never silently reverts an admin's approve/reject.
    """
    conn.execute(
        """
        INSERT INTO sources (
            source_id, source_type, title, url, playlist_url, external_id,
            doctors, topics, content_date, embedding_model
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id) DO UPDATE SET
            title = EXCLUDED.title,
            url = EXCLUDED.url,
            playlist_url = EXCLUDED.playlist_url,
            doctors = EXCLUDED.doctors,
            topics = EXCLUDED.topics,
            content_date = EXCLUDED.content_date,
            updated_at = NOW()
        """,
        (
            source.source_id,
            source.source_type,
            source.title,
            source.url,
            source.playlist_url,
            source.external_id,
            source.doctors,
            source.topics,
            source.content_date,
            source.embedding_model,
        ),
    )


@dataclass
class UpsertResult:
    written: int
    skipped: int


def upsert_chunks(
    conn: psycopg.Connection,
    source: SourceInput,
    chunks: list[ChunkInput],
) -> UpsertResult:
    """Content-hash-skip upsert: unchanged chunk text is a no-op write.

    chunk_id is deterministic (source_id + chunk_index), not random — unlike
    the legacy chmbot's uuid-suffixed ids (inventory §8.5), so re-ingesting
    the same source always targets the same rows instead of accumulating
    orphaned duplicates.
    """
    written = 0
    skipped = 0

    existing = {
        row["chunk_index"]: row["chunk_hash"]
        for row in conn.execute(
            "SELECT chunk_index, chunk_hash FROM chunks WHERE source_id = %s",
            (source.source_id,),
        ).fetchall()
    }

    for chunk in chunks:
        chunk_hash = content_hash(chunk.text)
        if existing.get(chunk.index) == chunk_hash:
            skipped += 1
            continue

        chunk_id = f"{source.source_id}:{chunk.index}"
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, source_id, source_type, chunk_index, text, text_length,
                embedding, speaker, speakers_in_chunk, timestamp_start, timestamp_end,
                duration_seconds, title, url, playlist_url, doctors, topics,
                content_date, embedding_model, chunk_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_id, chunk_index) DO UPDATE SET
                text = EXCLUDED.text,
                text_length = EXCLUDED.text_length,
                embedding = EXCLUDED.embedding,
                speaker = EXCLUDED.speaker,
                speakers_in_chunk = EXCLUDED.speakers_in_chunk,
                timestamp_start = EXCLUDED.timestamp_start,
                timestamp_end = EXCLUDED.timestamp_end,
                duration_seconds = EXCLUDED.duration_seconds,
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                playlist_url = EXCLUDED.playlist_url,
                doctors = EXCLUDED.doctors,
                topics = EXCLUDED.topics,
                content_date = EXCLUDED.content_date,
                embedding_model = EXCLUDED.embedding_model,
                chunk_hash = EXCLUDED.chunk_hash,
                ingested_at = NOW()
            """,
            (
                chunk_id,
                source.source_id,
                source.source_type,
                chunk.index,
                chunk.text,
                len(chunk.text),
                _vector_literal(chunk.embedding),
                chunk.speaker,
                chunk.speakers_in_chunk,
                chunk.timestamp_start,
                chunk.timestamp_end,
                chunk.duration_seconds,
                source.title,
                source.url,
                source.playlist_url,
                source.doctors,
                source.topics,
                source.content_date,
                source.embedding_model,
                chunk_hash,
            ),
        )
        written += 1

    conn.execute(
        "UPDATE sources SET chunk_count = %s, last_ingested_at = NOW(), updated_at = NOW() "
        "WHERE source_id = %s",
        (len(chunks), source.source_id),
    )

    return UpsertResult(written=written, skipped=skipped)
