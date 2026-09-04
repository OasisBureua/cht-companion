"""Database helpers for cht-companion (SCRUM-196 schema)."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
HELLO_SOURCE_ID = "curated:hello-world"
EMBED_DIM = 1024
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), row_factory=dict_row)


def _split_sql(script: str) -> list[str]:
    """Split a SQL file into statements (no procedure bodies in our migrations)."""
    cleaned = re.sub(r"--.*?$", "", script, flags=re.MULTILINE)
    parts = [p.strip() for p in cleaned.split(";")]
    return [p for p in parts if p]


def _execute_script(conn: psycopg.Connection, script: str) -> None:
    for statement in _split_sql(script):
        conn.execute(statement)


def check_connectivity() -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT current_database() AS database, current_user AS user, "
            "version() AS version, NOW() AS now"
        ).fetchone()
        assert row is not None
        return {
            "ok": True,
            "database": row["database"],
            "user": row["user"],
            "server_time": row["now"].isoformat(),
            "version": row["version"].split(",")[0],
        }


def schema_status() -> dict[str, Any]:
    with connect() as conn:
        extensions = {
            r["extname"]: r["extversion"]
            for r in conn.execute(
                "SELECT extname, extversion FROM pg_extension "
                "WHERE extname IN ('vector', 'pgcrypto')"
            ).fetchall()
        }
        tables = {
            r["tablename"]: True
            for r in conn.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' "
                "AND tablename IN ('sources', 'chunks', 'ingest_jobs')"
            ).fetchall()
        }
        return {
            "extensions": extensions,
            "tables": {
                "sources": "sources" in tables,
                "chunks": "chunks" in tables,
                "ingest_jobs": "ingest_jobs" in tables,
            },
            "ready": (
                "vector" in extensions
                and "pgcrypto" in extensions
                and all(tables.get(t) for t in ("sources", "chunks", "ingest_jobs"))
            ),
        }


def list_migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def pending_migrations(conn: psycopg.Connection | None = None) -> list[str]:
    """Filenames on disk that are not yet recorded in schema_migrations."""
    sql_files = list_migration_files()
    if not sql_files:
        return []

    own_conn = conn is None
    if own_conn:
        conn = connect()
    assert conn is not None
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {
            r["filename"]
            for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()
        }
        return [p.name for p in sql_files if p.name not in applied]
    finally:
        if own_conn:
            conn.close()


def apply_migrations() -> list[str]:
    """Apply only pending SQL migrations (alembic/prisma-style).

    No-op when schema_migrations already has every file on disk.
    Concurrent ECS tasks serialize via pg_advisory_lock.
    """
    sql_files = list_migration_files()
    if not sql_files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    lock_key = 196_001
    applied: list[str] = []

    with connect() as conn:
        # Fast path: nothing new → skip lock work beyond a quick check.
        pending = pending_migrations(conn)
        if not pending:
            return []

        conn.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
        try:
            # Re-check under lock (another task may have applied meanwhile).
            pending = pending_migrations(conn)
            by_name = {p.name: p for p in sql_files}
            for name in pending:
                path = by_name[name]
                _execute_script(conn, path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (name,),
                )
                applied.append(name)
            conn.commit()
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
    return applied


def _zero_embedding() -> str:
    return "[" + ",".join(["0"] * EMBED_DIM) + "]"


def hello_world() -> dict[str, Any]:
    """Insert/read a curated hello-world source + chunk to prove schema + pgvector."""
    text = "Hello from CHT Companion KB schema. Connectivity and upserts work."
    chunk_id = f"{HELLO_SOURCE_ID}:chunk:0"
    chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    embedding = _zero_embedding()

    with connect() as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO sources (
                    source_id, source_type, title, url, status,
                    embedding_model, chunk_count, doctors, topics
                ) VALUES (
                    %s, 'curated_doc', 'Hello World', 'https://communityhealth.media/',
                    'approved', %s, 1, '{}', '{hello}'
                )
                ON CONFLICT (source_id) DO UPDATE SET
                    updated_at = NOW(),
                    status = EXCLUDED.status,
                    chunk_count = EXCLUDED.chunk_count
                """,
                (HELLO_SOURCE_ID, EMBEDDING_MODEL),
            )
            conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, source_id, source_type, chunk_index,
                    text, text_length, embedding, title, url,
                    status, embedding_model, chunk_hash, topics
                ) VALUES (
                    %s, %s, 'curated_doc', 0,
                    %s, %s, %s::vector, 'Hello World',
                    'https://communityhealth.media/',
                    'approved', %s, %s, '{hello}'
                )
                ON CONFLICT (chunk_id) DO UPDATE SET
                    text = EXCLUDED.text,
                    text_length = EXCLUDED.text_length,
                    embedding = EXCLUDED.embedding,
                    chunk_hash = EXCLUDED.chunk_hash,
                    status = EXCLUDED.status,
                    ingested_at = NOW()
                """,
                (
                    chunk_id,
                    HELLO_SOURCE_ID,
                    text,
                    len(text),
                    embedding,
                    EMBEDDING_MODEL,
                    chunk_hash,
                ),
            )
            job = conn.execute(
                """
                INSERT INTO ingest_jobs (
                    source_id, kind, status, triggered_by,
                    chunks_before, chunks_after, chunks_skipped,
                    started_at, completed_at
                ) VALUES (
                    %s, 'initial', 'succeeded', 'hello-world',
                    0, 1, 0, NOW(), NOW()
                )
                RETURNING job_id
                """,
                (HELLO_SOURCE_ID,),
            ).fetchone()

        row = conn.execute(
            """
            SELECT c.chunk_id, c.source_id, c.title, c.status,
                   c.embedding_model, c.text_length,
                   (c.embedding <=> %s::vector) AS distance
            FROM chunks c
            WHERE c.chunk_id = %s AND c.status = 'approved'
            """,
            (embedding, chunk_id),
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM sources) AS sources,
              (SELECT COUNT(*) FROM chunks) AS chunks,
              (SELECT COUNT(*) FROM ingest_jobs) AS ingest_jobs
            """
        ).fetchone()

    assert row is not None
    assert counts is not None
    return {
        "ok": True,
        "message": "hello-world schema check passed",
        "source_id": HELLO_SOURCE_ID,
        "chunk_id": row["chunk_id"],
        "title": row["title"],
        "status": row["status"],
        "embedding_model": row["embedding_model"],
        "distance_to_zero_vector": float(row["distance"]),
        "job_id": str(job["job_id"]) if job else None,
        "counts": {
            "sources": counts["sources"],
            "chunks": counts["chunks"],
            "ingest_jobs": counts["ingest_jobs"],
        },
    }
