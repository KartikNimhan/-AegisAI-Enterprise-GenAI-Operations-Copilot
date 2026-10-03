"""Request/response schemas for the chat completion endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.llm.schemas import ModelRole, TokenUsage


class ChatCompletionRequest(BaseModel):
    conversation_id: uuid.UUID | None = Field(
        default=None,
        description="Existing conversation to continue. Omit to start a new one.",
    )
    message: str = Field(min_length=1, description="The user message to send to the model.")
    model_role: ModelRole = ModelRole.PRIMARY


class ChatCompletionResponse(BaseModel):
    conversation_id: uuid.UUID
    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: TokenUsage
    request_id: str | None = None


class ChatCompletionStreamChunk(BaseModel):
    """One SSE `data:` payload for the streaming chat endpoint.

    `conversation_id` is repeated on every chunk (not just the first) so a
    stateless SSE client always knows which conversation it's watching,
    including the common case of a brand-new conversation whose id wasn't
    known before the first chunk arrived.
    """

    conversation_id: uuid.UUID
    delta: str
    model: str | None = None
    finish_reason: str | None = None
    is_final: bool = False
    usage: TokenUsage | None = None
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
