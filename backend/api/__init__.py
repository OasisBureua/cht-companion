"""HTTP + SSE API package (SCRUM-195)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.config import API_VERSION, IMAGE_TAG
from api.routers import admin, chat, debug, health
from api.schemas import ApiError, ApiErrorBody
from db import apply_migrations

logger = logging.getLogger("cht-companion")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Apply pending KB migrations when DATABASE_URL is set (no-op if up to date)."""
    if os.environ.get("DATABASE_URL"):
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

    return application
