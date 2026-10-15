"""Dev-only debug routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from api.config import is_dev
from db import check_connectivity, hello_world, schema_status

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/kb-hello")
def kb_hello() -> dict:
    """Upsert hello-world row and verify pgvector read."""
    if not is_dev():
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
