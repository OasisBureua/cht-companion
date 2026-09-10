"""KB admin endpoints — SCRUM-195 §2.4, wired to SCRUM-196 §5.2 transactional store."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api import admin_store
from api.auth import CallerContext, caller_context, require_admin, require_bff_auth
from api.schemas import (
    ApiError,
    ApiErrorBody,
    ApproveBody,
    KbStatsResponse,
    ReindexResponse,
    RejectBody,
    SoftDeleteBody,
    SourceDetailResponse,
    SourceListItem,
    SourceListResponse,
)
from db import database_configured

router = APIRouter(prefix="/admin", tags=["admin"])


def _admin_deps(
    _auth: None = Depends(require_bff_auth),
    ctx: CallerContext = Depends(caller_context),
) -> CallerContext:
    return require_admin(ctx)


def _require_if_match(if_match: str | None) -> int:
    """Optimistic concurrency — SCRUM-195 §2.4 If-Match: <version>."""
    if if_match is None or if_match.strip() == "":
        raise HTTPException(
            status_code=428,
            detail=ApiError(
                error=ApiErrorBody(
                    code="validation",
                    message="If-Match header with source version is required",
                    field="If-Match",
                )
            ).model_dump(),
        )
    try:
        return int(if_match.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=ApiError(
                error=ApiErrorBody(
                    code="validation",
                    message="If-Match must be an integer version",
                    field="If-Match",
                )
            ).model_dump(),
        ) from exc


def _service_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=ApiError(error=ApiErrorBody(code="internal", message=detail)).model_dump(),
    )


def _not_found(source_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=ApiError(
            error=ApiErrorBody(
                code="validation", message=f"Source not found: {source_id}", field="source_id"
            )
        ).model_dump(),
    )


def _version_conflict(current_version: int) -> HTTPException:
    """current_version nests inside error (ApiErrorBody) — keeps every error
    response a valid ApiError instance instead of a top-level sibling field.
    """
    return HTTPException(
        status_code=409,
        detail=ApiError(
            error=ApiErrorBody(
                code="validation",
                message="If-Match version is stale",
                field="If-Match",
                current_version=current_version,
            )
        ).model_dump(),
    )


def _source_list_item(row: dict) -> SourceListItem:
    return SourceListItem(
        source_id=row["source_id"],
        source_type=row["source_type"],
        title=row["title"],
        url=row["url"],
        status=row["status"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"].isoformat(),
        approved_by=row["approved_by"],
        approved_at=row["approved_at"].isoformat() if row["approved_at"] else None,
        version=row["version"],
    )


@router.get("/sources", response_model=SourceListResponse)
def list_sources(
    _ctx: CallerContext = Depends(_admin_deps),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> SourceListResponse:
    if not database_configured():
        return SourceListResponse(items=[], next_cursor=None, total=0)

    page = admin_store.list_sources(status=status, cursor=cursor, limit=limit)
    items = [_source_list_item(row) for row in page.items]
    return SourceListResponse(items=items, next_cursor=page.next_cursor, total=page.total)


@router.get("/sources/{source_id}", response_model=SourceDetailResponse)
def get_source(
    source_id: str,
    _ctx: CallerContext = Depends(_admin_deps),
) -> SourceDetailResponse:
    if not database_configured():
        raise _not_found(source_id)

    try:
        detail = admin_store.get_source(source_id)
    except admin_store.SourceNotFound:
        raise _not_found(source_id) from None

    return SourceDetailResponse(
        source=_source_list_item(detail["source"]),
        chunks=detail["chunks"],
        detail=None,
    )


@router.post("/sources/{source_id}/approve")
def approve_source(
    source_id: str,
    body: ApproveBody,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: CallerContext = Depends(_admin_deps),
) -> dict:
    """Approve pending source — synchronous transactional UPDATE (SCRUM-196 §5.2)."""
    version = _require_if_match(if_match)
    _ = body  # note is accepted but not persisted (no column for it in sources)

    if not database_configured():
        raise _service_unavailable("database not configured")

    try:
        result = admin_store.approve_source(source_id, version, approved_by=ctx.user_id)
    except admin_store.SourceNotFound:
        raise _not_found(source_id) from None
    except admin_store.VersionConflict as exc:
        raise _version_conflict(exc.current_version) from None

    return {"ok": True, **result}


@router.post("/sources/{source_id}/reject")
def reject_source(
    source_id: str,
    body: RejectBody,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: CallerContext = Depends(_admin_deps),
) -> dict:
    """Reject pending source — synchronous transactional UPDATE (SCRUM-196 §5.2)."""
    version = _require_if_match(if_match)

    if not database_configured():
        raise _service_unavailable("database not configured")

    try:
        result = admin_store.reject_source(
            source_id, version, rejected_by=ctx.user_id, reason=body.reason
        )
    except admin_store.SourceNotFound:
        raise _not_found(source_id) from None
    except admin_store.VersionConflict as exc:
        raise _version_conflict(exc.current_version) from None

    return {"ok": True, **result}


@router.delete("/sources/{source_id}")
def soft_delete_source(
    source_id: str,
    body: SoftDeleteBody,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: CallerContext = Depends(_admin_deps),
) -> dict:
    """Soft-delete source + cascade to chunks — synchronous (SCRUM-196 §5.2)."""
    version = _require_if_match(if_match)

    if not database_configured():
        raise _service_unavailable("database not configured")

    try:
        result = admin_store.soft_delete_source(
            source_id, version, deleted_by=ctx.user_id, reason=body.reason
        )
    except admin_store.SourceNotFound:
        raise _not_found(source_id) from None
    except admin_store.VersionConflict as exc:
        raise _version_conflict(exc.current_version) from None

    return {"ok": True, **result}


@router.post(
    "/sources/{source_id}/reindex",
    response_model=ReindexResponse,
    status_code=202,
)
def reindex_source(
    source_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: CallerContext = Depends(_admin_deps),
) -> ReindexResponse:
    """Enqueue re-embed job (202 + job_id): writes a real ingest_jobs row.

    No queue/worker consumes this row yet (out of scope for this PR) — the
    job sits at status='queued' until a worker exists. That's an honest,
    inspectable state (visible via GET /admin/sources/{id} or a future
    /admin/jobs endpoint), unlike the previous behavior of returning a
    random UUID that corresponded to nothing in the database.
    """
    _require_if_match(if_match)

    if not database_configured():
        raise _service_unavailable("database not configured")

    try:
        result = admin_store.enqueue_reindex(source_id, triggered_by=ctx.user_id)
    except admin_store.SourceNotFound:
        raise _not_found(source_id) from None

    return ReindexResponse(job_id=result["job_id"], status="queued")


@router.get("/kb/stats", response_model=KbStatsResponse)
def kb_stats(_ctx: CallerContext = Depends(_admin_deps)) -> KbStatsResponse:
    if not database_configured():
        return KbStatsResponse(detail=None)

    counts = admin_store.kb_stats()
    return KbStatsResponse(**counts, detail=None)
