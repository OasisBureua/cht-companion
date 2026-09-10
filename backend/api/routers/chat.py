"""POST /chat SSE — SCRUM-195 §2.1 / §4 (retrieval + Bedrock generation wired)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.auth import CallerContext, caller_context, require_bff_auth
from api.config import API_VERSION
from api.ratelimit import RateLimitExceeded, check_chat_rate_limit
from api.schemas import ApiError, ApiErrorBody, ChatRequest
from api.sse import placeholder_chat_stream, retrieval_chat_stream
from db import database_configured

router = APIRouter(tags=["chat"])


def _rate_limited(exc: RateLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=ApiError(
            error=ApiErrorBody(
                code="rate_limited",
                message="Too many chat requests; slow down.",
                retry_after_ms=exc.retry_after_ms,
            )
        ).model_dump(),
        headers={"Retry-After": str(max(exc.retry_after_ms // 1000, 1))},
    )


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    _auth: None = Depends(require_bff_auth),
    ctx: CallerContext = Depends(caller_context),
) -> StreamingResponse:
    """SSE RAG answer. Retrieval (SCRUM-196) and Bedrock generation (SCRUM-195 §4.2)
    are both wired when DATABASE_URL is configured; falls back to the fixed
    placeholder stream otherwise (local dev without a DB).
    """
    _ = request  # reserved for Request.is_disconnected() cancellation

    try:
        check_chat_rate_limit(ctx.user_id)
    except RateLimitExceeded as exc:
        raise _rate_limited(exc) from None
    except ConnectionError as exc:
        # Fail-closed in prod (rate-limit store unreachable) per SCRUM-195 §8
        # dependency-failure-matrix policy — same posture as database_configured().
        raise HTTPException(
            status_code=503,
            detail=ApiError(
                error=ApiErrorBody(code="internal", message="rate limit store unavailable")
            ).model_dump(),
        ) from exc

    stream = (
        retrieval_chat_stream(body.query, ctx.request_id, shim=True)
        if database_configured()
        else placeholder_chat_stream(body.query, ctx.request_id, shim=True)
    )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Api-Version": API_VERSION,
            "X-Request-Id": ctx.request_id,
        },
    )
