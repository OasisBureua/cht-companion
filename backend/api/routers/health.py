"""Health endpoints — SCRUM-195 §2.1 / §2.3."""

from __future__ import annotations

import os

from fastapi import APIRouter

from api.config import API_VERSION, IMAGE_TAG
from api.schemas import HealthChecks, HealthResponse
from db import check_connectivity, schema_status

router = APIRouter(tags=["health"])


def _bedrock_check() -> str:
    """Placeholder: real check = Bedrock list_foundation_models within 3s."""
    return "degraded"


def _database_check() -> tuple[str, dict | None]:
    if not os.environ.get("DATABASE_URL"):
        return "unavailable", None
    try:
        connectivity = check_connectivity()
        schema = schema_status()
        if connectivity.get("ok") and schema.get("ready"):
            return "ok", {"connectivity": connectivity, "schema": schema}
        return "degraded", {"connectivity": connectivity, "schema": schema}
    except Exception as exc:  # noqa: BLE001
        return "unavailable", {"detail": str(exc)}


def _aggregate_status(database: str, bedrock: str) -> str:
    if database == "unavailable" and bedrock == "unavailable":
        return "unhealthy"
    if database == "ok" and bedrock == "ok":
        return "ok"
    return "degraded"


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    """Process up only — never touches DB or Bedrock."""
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        image_tag=IMAGE_TAG,
        checks=HealthChecks(database="ok", bedrock="ok"),
    )


@router.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    """DB + Bedrock reachability (placeholders for Bedrock)."""
    database, _extra = _database_check()
    bedrock = _bedrock_check()
    return HealthResponse(
        status=_aggregate_status(database, bedrock),
        version=API_VERSION,
        image_tag=IMAGE_TAG,
        checks=HealthChecks(database=database, bedrock=bedrock),  # type: ignore[arg-type]
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Docker HEALTHCHECK aggregate — same shape as /health/ready."""
    return health_ready()
