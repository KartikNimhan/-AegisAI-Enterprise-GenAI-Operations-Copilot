"""Request/response schemas for the chat completion endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm.schemas import ModelRole, TokenUsage


class ChatCompletionRequest(BaseModel):
    message: str = Field(min_length=1, description="The user message to send to the model.")
    model_role: ModelRole = ModelRole.PRIMARY


class ChatCompletionResponse(BaseModel):
    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: TokenUsage
    request_id: str | None = None


class ChatCompletionStreamErrorDetail(BaseModel):
    code: str
    message: str


class ChatCompletionStreamError(BaseModel):
    """Terminal SSE event emitted when a stream fails mid-flight.

    The HTTP status is already committed by the time streaming starts, so a
    provider error can't become a 4xx/5xx — it's surfaced as a final event
    on the stream instead.
    """

    error: ChatCompletionStreamErrorDetail
