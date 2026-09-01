"""cht-companion RAG API — FastAPI on Fargate, Service Connect :8080."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="cht-companion",
    description="Members-only RAG chat API (called only via CHT NestJS BFF).",
    version=os.environ.get("IMAGE_TAG", "local"),
)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


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
