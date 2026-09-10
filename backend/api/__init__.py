"""HTTP + SSE API package (SCRUM-195)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.config import API_VERSION, IMAGE_TAG
from api.logging_config import configure_app_logging
from api.routers import admin, chat, debug, health
from api.schemas import ApiError, ApiErrorBody
from db import apply_migrations, database_configured

configure_app_logging()
logger = logging.getLogger("cht-companion")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Apply pending KB migrations when DATABASE_URL is set (no-op if up to date)."""
    configure_app_logging()
    if database_configured():
        try:
            from db import pending_migrations

            pending_before = pending_migrations()
        except Exception:  # noqa: BLE001
            pending_before = ["(unable to list)"]
        if pending_before:
            applied = apply_migrations()
            logger.info("KB migrations applied: %s", applied)
        else:
            logger.info("KB migrations: already up to date (none pending)")
    else:
        logger.warning("DATABASE_URL not set; skipping KB migrations")
    yield


def create_app() -> FastAPI:
    configure_app_logging()
    application = FastAPI(
        title="cht-companion",
        description="Members-only RAG chat API (called only via CHT NestJS BFF).",
        version=IMAGE_TAG,
        lifespan=lifespan,
    )

    application.include_router(health.router)
    application.include_router(chat.router)
    application.include_router(admin.router)
    application.include_router(debug.router)

    @application.middleware("http")
    async def add_api_version_header(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Api-Version", API_VERSION)
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Map FastAPI 422 → SCRUM-195 §5.2 HTTP 400 validation shape."""
        field = None
        message = "Validation failed"
        if exc.errors():
            err = exc.errors()[0]
            loc = err.get("loc") or ()
            field = str(loc[-1]) if loc else None
            message = err.get("msg", message)
        body = ApiError(
            error=ApiErrorBody(code="validation", message=message, field=field)
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        """Unwrap the {"detail": ...} envelope FastAPI adds by default.

        Every raise HTTPException(..., detail=ApiError(...).model_dump()) in this
        codebase already builds the flat {"error": {...}} shape from SCRUM-195 §5.2 —
        this handler just stops FastAPI from re-wrapping it under "detail".
        """
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            content = exc.detail
        else:
            content = ApiError(
                error=ApiErrorBody(code="internal", message=str(exc.detail))
            ).model_dump()
        headers = getattr(exc, "headers", None)
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    return application
