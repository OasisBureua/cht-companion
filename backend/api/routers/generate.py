"""POST /generate: plain Bedrock completion, no retrieval.

For callers (cht-reports) that assemble their own context (a report's
transcript + survey input packet) rather than using this service's RAG
chat pipeline. Distinct from /chat: no vector search, no chat history, no
hardcoded chat system prompt. The caller supplies both system_prompt and
user_content directly.

Auth reuses require_bff_auth (X-BFF-Auth shared secret) as-is. This is a
genuine service-to-service call (cht-reports over Service Connect, not a
browser via the NestJS BFF), but the underlying mechanism, whether the
caller knows the shared secret, is the same regardless of who's calling,
and cht-reports gets provisioned the same COMPANION_INTERNAL_SECRET via
Secrets Manager rather than this needing a second auth scheme.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from api.auth import require_bff_auth
from api.bedrock import GenerationError, generate_completion
from api.config import API_VERSION
from api.ratelimit import RateLimitExceeded, check_generate_rate_limit
from api.schemas import ApiError, ApiErrorBody, GenerateRequest, GenerateResponse
from api.ulid import new_ulid

router = APIRouter(tags=["generate"])


def _rate_limited(exc: RateLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=ApiError(
            error=ApiErrorBody(
                code="rate_limited",
                message="Too many /generate requests; slow down.",
                retry_after_ms=exc.retry_after_ms,
            )
        ).model_dump(),
        headers={"Retry-After": str(max(exc.retry_after_ms // 1000, 1))},
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    body: GenerateRequest,
    _auth: None = Depends(require_bff_auth),
    x_client: str | None = Header(default=None, alias="X-Client"),
) -> GenerateResponse:
    request_id = new_ulid()

    try:
        # Keyed by the caller-supplied X-Client header (same header /chat
        # already defines, just not required there). Falls back to a
        # shared "unknown-caller" bucket rather than failing the request if
        # a caller omits it. cht-reports sends X-Client: cht-reports.
        check_generate_rate_limit(x_client)
    except RateLimitExceeded as exc:
        raise _rate_limited(exc) from None
    except ConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail=ApiError(
                error=ApiErrorBody(code="internal", message="rate limit store unavailable")
            ).model_dump(),
        ) from exc

    try:
        text, finish_reason = generate_completion(
            body.system_prompt,
            body.user_content,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            request_id=request_id,
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=502,
            detail=ApiError(
                error=ApiErrorBody(code="llm_timeout", message=str(exc))
            ).model_dump(),
        ) from exc

    return GenerateResponse(text=text, finish_reason=finish_reason, request_id=request_id)
