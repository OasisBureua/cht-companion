"""Request/response models — SCRUM-195 API contract (rev 2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SourceType = Literal["youtube_caption", "catalog_clip", "curated_doc"]
SourceStatus = Literal["pending", "approved", "rejected", "soft_deleted"]
FinishReason = Literal["complete", "truncated", "error", "cancelled"]
ErrorCode = Literal[
    "rate_limited",
    "retrieval_failed",
    "retrieval_degraded",
    "llm_refused",
    "llm_timeout",
    "internal",
    "validation",
    "unauthorized",
]
CheckStatus = Literal["ok", "degraded", "unavailable"]
HealthStatus = Literal["ok", "degraded", "unhealthy"]


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=8192)


class ChatOptions(BaseModel):
    max_tokens: int = Field(default=1024, ge=1, le=2048)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class ChatRequest(BaseModel):
    """POST /chat body. Extra fields ignored for BFF forward-compat."""

    model_config = {"extra": "ignore"}

    query: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None
    history: list[HistoryTurn] = Field(default_factory=list)
    options: ChatOptions = Field(default_factory=ChatOptions)

    @field_validator("history")
    @classmethod
    def trim_history(cls, value: list[HistoryTurn]) -> list[HistoryTurn]:
        # Contract: cap 20 turns, trim oldest (front).
        if len(value) > 20:
            return value[-20:]
        return value


class HealthChecks(BaseModel):
    database: CheckStatus = "unavailable"
    bedrock: CheckStatus = "unavailable"


class HealthResponse(BaseModel):
    status: HealthStatus
    version: str
    image_tag: str
    checks: HealthChecks


class ApiErrorBody(BaseModel):
    code: str
    message: str
    field: str | None = None
    retry_after_ms: int | None = None


class ApiError(BaseModel):
    error: ApiErrorBody


# --- SSE payload shapes (emitted as JSON in data: lines) ---


class TokenEvent(BaseModel):
    text: str
    index: int


class CitationEvent(BaseModel):
    citation_id: str
    source_id: str
    chunk_id: str
    source_type: SourceType | str
    title: str
    url: str
    playlist_url: str | None = None
    snippet: str
    timestamp: int | None = None


class ErrorEvent(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    retry_after_ms: int | None = None


class LatencyMs(BaseModel):
    retrieval: int
    first_token: int
    total: int


class DoneEvent(BaseModel):
    finish_reason: FinishReason
    tokens_generated: int
    citations_emitted: int
    latency_ms: LatencyMs
    request_id: str


# --- Admin (SCRUM-195 §2.4) ---


class SourceListItem(BaseModel):
    source_id: str
    source_type: SourceType | str
    title: str
    url: str
    status: SourceStatus | str
    chunk_count: int
    created_at: str
    approved_by: str | None = None
    approved_at: str | None = None
    version: int = 1


class SourceListResponse(BaseModel):
    items: list[SourceListItem]
    next_cursor: str | None
    total: int


class ApproveBody(BaseModel):
    note: str | None = None


class SoftDeleteBody(BaseModel):
    reason: str | None = None


class ReindexResponse(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"


class KbStatsResponse(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    soft_deleted: int = 0
    sources: int = 0
    chunks: int = 0
    detail: str | None = "placeholder — wire to SCRUM-196 aggregates"


class SourceDetailResponse(BaseModel):
    source: SourceListItem
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    detail: str | None = "placeholder — wire to sources + chunks tables"
