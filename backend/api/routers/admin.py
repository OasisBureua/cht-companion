"""KB admin endpoints — SCRUM-195 §2.4 (placeholders; wire to SCRUM-196 later)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api.auth import CallerContext, caller_context, require_admin, require_bff_auth
from api.schemas import (
    ApiError,
    ApiErrorBody,
    ApproveBody,
    KbStatsResponse,
    ReindexResponse,
    SoftDeleteBody,
    SourceDetailResponse,
    SourceListResponse,
)

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


@router.get("/sources", response_model=SourceListResponse)
def list_sources(
    _ctx: CallerContext = Depends(_admin_deps),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> SourceListResponse:
    """List sources with cursor pagination. Placeholder empty page."""
    _ = (status, cursor, limit)
    return SourceListResponse(items=[], next_cursor=None, total=0)


@router.get("/sources/{source_id}", response_model=SourceDetailResponse)
def get_source(
    source_id: str,
    _ctx: CallerContext = Depends(_admin_deps),
) -> SourceDetailResponse:
    """Source detail + chunks. Placeholder 404 until DB wired."""
    raise HTTPException(
        status_code=404,
        detail=ApiError(
            error=ApiErrorBody(
                code="validation",
                message=f"Source not found (placeholder): {source_id}",
                field="source_id",
            )
        ).model_dump(),
    )


@router.post("/sources/{source_id}/approve")
def approve_source(
    source_id: str,
    body: ApproveBody,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: CallerContext = Depends(_admin_deps),
) -> dict:
    """Approve pending source (sync 200). Placeholder."""
    version = _require_if_match(if_match)
    return {
        "ok": True,
        "placeholder": True,
        "source_id": source_id,
        "status": "approved",
        "approved_by": ctx.user_id,
        "note": body.note,
        "version_read": version,
        "detail": "TODO: transactional UPDATE sources + chunks (SCRUM-196 §5.2)",
    }


@router.delete("/sources/{source_id}")
def soft_delete_source(
    source_id: str,
    body: SoftDeleteBody,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: CallerContext = Depends(_admin_deps),
) -> dict:
    """Soft-delete source + chunks (sync 200). Placeholder."""
    version = _require_if_match(if_match)
    return {
        "ok": True,
        "placeholder": True,
        "source_id": source_id,
        "status": "soft_deleted",
        "reason": body.reason,
        "deleted_by": ctx.user_id,
        "version_read": version,
        "detail": "TODO: transactional soft_delete on sources + chunks",
    }


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
    """Enqueue re-embed job (202 + job_id). Placeholder UUID."""
    _ = (ctx, _require_if_match(if_match), source_id)
    return ReindexResponse(job_id=str(uuid.uuid4()), status="queued")


@router.get("/kb/stats", response_model=KbStatsResponse)
def kb_stats(_ctx: CallerContext = Depends(_admin_deps)) -> KbStatsResponse:
    """Counts by status. Placeholder zeros."""
    return KbStatsResponse()
