"""cht-companion RAG API — FastAPI on Fargate, Service Connect :8080."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db import apply_migrations, check_connectivity, hello_world, schema_status

logger = logging.getLogger("cht-companion")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Local uvicorn safety net: apply pending migrations if DATABASE_URL is set.

    Container deploys use docker-entrypoint.sh (same as contenthub alembic /
    platform-tool prisma migrate deploy). apply_migrations() is a no-op when
    nothing is pending.
    """
    if os.environ.get("DATABASE_URL"):
        pending_before = None
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


app = FastAPI(
    title="cht-companion",
    description="Members-only RAG chat API (called only via CHT NestJS BFF).",
    version=os.environ.get("IMAGE_TAG", "local"),
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)


def _debug_enabled() -> bool:
    env = os.environ.get("CHT_ENVIRONMENT", "development").lower()
    return env in {"development", "dev", "local"} or os.environ.get(
        "ALLOW_KB_DEBUG", ""
    ).lower() in {"1", "true", "yes"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict:
    """Ready when Postgres is reachable and KB schema is present."""
    if not os.environ.get("DATABASE_URL"):
        return {
            "status": "degraded",
            "version": os.environ.get("IMAGE_TAG", "local"),
            "checks": {"database": "unavailable"},
            "detail": "DATABASE_URL not set",
        }
    try:
        connectivity = check_connectivity()
        schema = schema_status()
        db_ok = connectivity.get("ok") and schema.get("ready")
        return {
            "status": "ok" if db_ok else "degraded",
            "version": os.environ.get("IMAGE_TAG", "local"),
            "checks": {
                "database": "ok" if db_ok else "degraded",
            },
            "database": connectivity,
            "schema": schema,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unhealthy",
            "version": os.environ.get("IMAGE_TAG", "local"),
            "checks": {"database": "unavailable"},
            "detail": str(exc),
        }


@app.post("/debug/kb-hello")
def kb_hello() -> dict:
    """Dev-only: upsert hello-world row and verify pgvector read (schema already on startup)."""
    if not _debug_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="DATABASE_URL not set")
    try:
        return {
            "ok": True,
            "connectivity": check_connectivity(),
            "schema": schema_status(),
            "hello": hello_world(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _placeholder_tokens(query: str) -> AsyncIterator[str]:
    """Scaffold stream until Bedrock + pgvector retrieval is wired."""
    text = (
        "CHT Companion received your question but the knowledge base is not "
        f"connected yet. You asked: {query.strip()}"
    )
    for word in text.split(" "):
        payload = json.dumps({"text": f"{word} "})
        yield f"data: {payload}\n\n"
        await asyncio.sleep(0)
    yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _placeholder_tokens(body.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
