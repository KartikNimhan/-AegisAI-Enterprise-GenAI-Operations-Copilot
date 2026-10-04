"""Provider-neutral request/response models for the LLM gateway.

Nothing in this module may depend on a provider SDK. `providers/groq.py` is
responsible for translating Groq's SDK objects into these types.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

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
    # Added in Milestone 6 for tool calling: a TOOL message carries one
    # tool's result back to the model, correlated to the ToolCall that
    # requested it via `tool_call_id`.
    TOOL = "tool"


class ToolCall(BaseModel):
    """One tool invocation the model requested — provider-neutral.

    `arguments` is deliberately the raw JSON string the provider returned,
    not a parsed dict: the model's output is untrusted input (it "does not
    always generate valid JSON", per Groq's own SDK docs), so parsing and
    validation happen at the tool-execution boundary
    (`app.agents.tools.base.ToolRegistry`), not here.
    """

    id: str
    name: str
    arguments: str


class ToolSpec(BaseModel):
    """A tool's schema as advertised to the LLM provider — name,
    description, and a JSON Schema for its arguments. Translated from
    `app.agents.tools.base.ToolDefinition` (the richer, application-level
    tool abstraction with an actual executor) at the point a call is made;
    the LLM gateway and providers never see anything beyond this schema.
    """

    name: str
    description: str
    parameters: dict[str, Any]


class ChatMessage(BaseModel):
    role: ChatRole
    # Empty, not absent: an ASSISTANT message that only requests tool calls
    # has no natural-language content yet, but every provider message still
    # needs a content field.
    content: str = ""
    # Set only on an ASSISTANT message that requested tool calls.
    tool_calls: list[ToolCall] | None = None
    # Set only on a TOOL message, naming the ToolCall.id it answers.
    tool_call_id: str | None = None


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
    # Populated when the model requested one or more tool calls instead of
    # (or alongside) a text answer — typically with `finish_reason ==
    # "tool_calls"` and `content == ""`, though a provider may set both.
    tool_calls: list[ToolCall] | None = None


class StreamChunk(BaseModel):
    """A normalized, provider-neutral chunk of a streamed completion."""

    delta: str = ""
    model: str | None = None
    finish_reason: str | None = None
    is_final: bool = False
    usage: TokenUsage | None = None
    request_id: str | None = None
