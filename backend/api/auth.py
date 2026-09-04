"""BFF → companion auth (SCRUM-195 §3). Placeholder until Secrets Manager is wired."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from api import config
from api.schemas import ApiError, ApiErrorBody


@dataclass
class CallerContext:
    """Identity forwarded by the NestJS BFF (no Cognito JWT on companion)."""

    request_id: str
    user_id: str | None
    session_id: str | None
    user_role: str | None
    client: str | None


def _unauthorized(message: str = "Missing or invalid X-BFF-Auth") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=ApiError(
            error=ApiErrorBody(code="unauthorized", message=message)
        ).model_dump(),
    )


def _forbidden(message: str = "Admin role required") -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=ApiError(
            error=ApiErrorBody(code="unauthorized", message=message)
        ).model_dump(),
    )


def require_bff_auth(
    x_bff_auth: str | None = Header(default=None, alias="X-BFF-Auth"),
) -> None:
    """Enforce shared secret when COMPANION_INTERNAL_SECRET is configured.

    If the secret is unset (local scaffold), auth is skipped so unit tests and
    local uvicorn keep working. Once Terraform injects the secret, requests
    without a matching header get HTTP 401.
    """
    secret = config.BFF_AUTH_SECRET
    if not secret:
        return
    if not x_bff_auth:
        raise _unauthorized()
    valid = [secret]
    previous = config.BFF_AUTH_SECRET_PREVIOUS
    if previous:
        valid.append(previous)
    if not any(secrets.compare_digest(x_bff_auth, v) for v in valid):
        raise _unauthorized()


def caller_context(
    request: Request,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    x_client: str | None = Header(default=None, alias="X-Client"),
) -> CallerContext:
    request_id = (x_request_id or "").strip() or str(uuid.uuid4())
    request.state.request_id = request_id
    return CallerContext(
        request_id=request_id,
        user_id=x_user_id,
        session_id=x_session_id,
        user_role=(x_user_role or "").strip().lower() or None,
        client=x_client,
    )


def require_admin(ctx: CallerContext) -> CallerContext:
    if ctx.user_role != "admin":
        raise _forbidden()
    return ctx
