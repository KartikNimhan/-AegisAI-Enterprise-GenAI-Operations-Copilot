"""The provider-neutral interface every LLM provider must implement.

`LLMGateway` depends only on this interface, never on a concrete provider or
SDK. Adding a new provider (OpenAI, Azure OpenAI, Gemini, Anthropic, a local
model) means writing a new `providers/<name>.py` implementing `LLMProvider`
— no changes to the gateway, services, or API routes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.llm.schemas import ChatMessage, CompletionResponse, StreamChunk, ToolSpec


class LLMProvider(ABC):
    """Provider-neutral contract for chat completion (sync and streaming)."""

    name: str

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> CompletionResponse:
        """Returns a single, normalized completion. Must raise only LLMError
        subclasses. `tools`, when given, lets the model request a tool call
        instead of (or alongside) text content — see `CompletionResponse.tool_calls`.
        Not supported on `stream_complete`: tool-call decisions need the
        complete structured output, not token deltas (see ADR 008).
        """
        raise NotImplementedError

    @abstractmethod
    def stream_complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Yields normalized chunks as they arrive. Must raise only LLMError subclasses."""
        raise NotImplementedError
