"""Provider-neutral request/response models for the LLM gateway.

Nothing in this module may depend on a provider SDK. `providers/groq.py` is
responsible for translating Groq's SDK objects into these types.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ModelRole(StrEnum):
    """A deterministic, typed routing target — not a model name.

    The actual model name for each role is configured via environment
    variables (see `app.config.Settings`) so it can change without touching
    application code.
    """

    PRIMARY = "primary"
    FAST = "fast"
    SAFETY = "safety"


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class TokenUsage(BaseModel):
    """Token counts as reported by the provider.

    Fields are `None` rather than `0` when the provider didn't report them,
    so callers can distinguish "zero tokens" from "unknown".
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class CompletionResponse(BaseModel):
    """A normalized, provider-neutral chat completion result."""

    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    request_id: str | None = None


class StreamChunk(BaseModel):
    """A normalized, provider-neutral chunk of a streamed completion."""

    delta: str = ""
    model: str | None = None
    finish_reason: str | None = None
    is_final: bool = False
    usage: TokenUsage | None = None
    request_id: str | None = None
