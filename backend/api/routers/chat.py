"""POST /chat SSE — SCRUM-195 §2.1 / §4 (retrieval wired; Bedrock generation pending)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.auth import CallerContext, caller_context, require_bff_auth
from api.config import API_VERSION
from api.schemas import ChatRequest
from api.sse import placeholder_chat_stream, retrieval_chat_stream
from db import database_configured

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    _auth: None = Depends(require_bff_auth),
    ctx: CallerContext = Depends(caller_context),
) -> StreamingResponse:
    """SSE RAG answer. Retrieval is wired (SCRUM-196); Bedrock token streaming is
    still a placeholder (SCRUM-195 §4.2 TODO).
    """
    # TODO: rate limit by ctx.user_id (ElastiCache) — SCRUM-195 §8
    # TODO: stream real Bedrock tokens instead of the placeholder text — SCRUM-195 §4.2
    _ = request  # reserved for Request.is_disconnected() cancellation

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
