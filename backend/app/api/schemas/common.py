"""Shared API response schemas (health/readiness, error envelope)."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.core.limits import (
    MAX_EVIDENCE_CHARS,
    MAX_EXPRESSION_CHARS,
    MAX_MESSAGE_CHARS,
)

# A user-supplied message or question: surrounding whitespace is removed, so a blank or
# whitespace-only value is rejected (422) instead of reaching the model, and it is capped.
UserMessage = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
]
OptionalUserMessage = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_MESSAGE_CHARS)
]
ExpressionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_EXPRESSION_CHARS)
]
EvidenceText = Annotated[str, StringConstraints(max_length=MAX_EVIDENCE_CHARS)]


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessStatus(BaseModel):
    status: Literal["ready", "degraded"]
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
