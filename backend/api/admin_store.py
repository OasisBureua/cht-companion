"""Source admin CRUD — SCRUM-195 §2.4 / SCRUM-196 §5.2 (transactional, versioned)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from db import connect

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class VersionConflict(Exception):
    """Raised when If-Match doesn't match the row's current version."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"version conflict, current={current_version}")


class SourceNotFound(Exception):
    pass


@dataclass
class SourcePage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int


def _encode_cursor(created_at: str, source_id: str) -> str:
    return f"{created_at}|{source_id}"


def _decode_cursor(cursor: str) -> tuple[str, str]:
    created_at, _, source_id = cursor.partition("|")
    return created_at, source_id


def list_sources(
    *,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> SourcePage:
    """Keyset pagination on (created_at, source_id) — SCRUM-195 §2.4 response shape."""
    limit = max(1, min(limit, MAX_LIMIT))

    where = []
    params: list[Any] = []
    if status:
        where.append("status = %s")
        params.append(status)
    if cursor:
        created_at, source_id = _decode_cursor(cursor)
        where.append("(created_at, source_id) > (%s, %s)")
        params.extend([created_at, source_id])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM sources {('WHERE ' + where[0]) if status else ''}",
            [status] if status else [],
        ).fetchone()["n"]

        rows = conn.execute(
            f"""
            SELECT source_id, source_type, title, url, status, chunk_count,
                   created_at, approved_by, approved_at, version
            FROM sources
            {where_sql}
            ORDER BY created_at, source_id
            LIMIT %s
            """,
            [*params, limit + 1],
        ).fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode_cursor(rows[-1]["created_at"].isoformat(), rows[-1]["source_id"])
        if has_more and rows
        else None
    )

    return SourcePage(items=[dict(r) for r in rows], next_cursor=next_cursor, total=total)


def get_source(source_id: str) -> dict[str, Any]:
    with connect() as conn:
        source = conn.execute(
            """
            SELECT source_id, source_type, title, url, status, chunk_count,
                   created_at, approved_by, approved_at, rejected_reason, version
            FROM sources WHERE source_id = %s
            """,
            (source_id,),
        ).fetchone()
        if source is None:
            raise SourceNotFound(source_id)

        chunks = conn.execute(
            """
            SELECT chunk_id, chunk_index, text_length, status, timestamp_start
            FROM chunks WHERE source_id = %s
            ORDER BY chunk_index
            """,
            (source_id,),
        ).fetchall()

    return {"source": dict(source), "chunks": [dict(c) for c in chunks]}


_SQL_LITERALS = {"NOW()"}


def _transition(
    source_id: str,
    expected_version: int,
    updates: dict[str, Any],
    chunk_status: str,
) -> dict[str, Any]:
    """Shared transactional UPDATE for approve/reject/soft-delete — SCRUM-196 §5.2.

    One transaction: bump sources.version + set fields, cascade status to every
    chunk under that source. Optimistic lock on sources.version via WHERE clause;
    a zero-row UPDATE means the caller's If-Match was stale.
    """
    set_clauses = ", ".join(
        f"{k} = {v}" if v in _SQL_LITERALS else f"{k} = %({k})s" for k, v in updates.items()
    )
    params = {
        **{k: v for k, v in updates.items() if v not in _SQL_LITERALS},
        "source_id": source_id,
        "expected_version": expected_version,
    }

    with connect() as conn:
        with conn.transaction():
            updated = conn.execute(
                f"""
                UPDATE sources
                SET {set_clauses}, version = version + 1, updated_at = NOW()
                WHERE source_id = %(source_id)s AND version = %(expected_version)s
                RETURNING source_id, status, version
                """,
                params,
            ).fetchone()

            if updated is None:
                current = conn.execute(
                    "SELECT version FROM sources WHERE source_id = %s", (source_id,)
                ).fetchone()
                if current is None:
                    raise SourceNotFound(source_id)
                raise VersionConflict(current["version"])

            conn.execute(
                "UPDATE chunks SET status = %s WHERE source_id = %s",
                (chunk_status, source_id),
            )

    return dict(updated)


def approve_source(source_id: str, expected_version: int, *, approved_by: str | None) -> dict[str, Any]:
    return _transition(
        source_id,
        expected_version,
        {"status": "approved", "approved_by": approved_by, "approved_at": "NOW()"},
        chunk_status="approved",
    )


def reject_source(
    source_id: str, expected_version: int, *, rejected_by: str | None, reason: str | None
) -> dict[str, Any]:
    return _transition(
        source_id,
        expected_version,
        {"status": "rejected", "rejected_by": rejected_by, "rejected_reason": reason},
        chunk_status="rejected",
    )


def soft_delete_source(
    source_id: str, expected_version: int, *, deleted_by: str | None, reason: str | None
) -> dict[str, Any]:
    return _transition(
        source_id,
        expected_version,
        {"status": "soft_deleted", "rejected_by": deleted_by, "rejected_reason": reason},
        chunk_status="soft_deleted",
    )


def enqueue_reindex(source_id: str, *, triggered_by: str | None) -> dict[str, Any]:
    """Write a queued ingest_jobs row (kind='reindex') for source_id.

    This writes the job record only — no worker/queue consumes it yet
    (SCRUM-196 ingest worker is out of scope for this PR). A row with
    status='queued' and no started_at/completed_at is the correct, honest
    state until that worker exists; the caller (admin router) still returns
    202 with this row's job_id, matching the async-job contract shape.
    """
    with connect() as conn:
        source = conn.execute(
            "SELECT source_id, chunk_count FROM sources WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        if source is None:
            raise SourceNotFound(source_id)

        job = conn.execute(
            """
            INSERT INTO ingest_jobs (
                source_id, kind, status, triggered_by, chunks_before
            ) VALUES (
                %s, 'reindex', 'queued', %s, %s
            )
            RETURNING job_id
            """,
            (source_id, triggered_by, source["chunk_count"]),
        ).fetchone()

    return {"job_id": str(job["job_id"]), "status": "queued"}


def kb_stats() -> dict[str, int]:
    with connect() as conn:
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM sources GROUP BY status"
            ).fetchall()
        }
        totals = conn.execute(
            "SELECT (SELECT COUNT(*) FROM sources) AS sources, "
            "(SELECT COUNT(*) FROM chunks) AS chunks"
        ).fetchone()

    return {
        "pending": by_status.get("pending", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
        "soft_deleted": by_status.get("soft_deleted", 0),
        "sources": totals["sources"],
        "chunks": totals["chunks"],
    }
