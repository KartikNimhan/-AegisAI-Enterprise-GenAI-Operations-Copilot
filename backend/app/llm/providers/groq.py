"""Groq provider implementation.

This is the only module in the codebase allowed to import the `groq`
package. It translates between Groq's SDK types and the provider-neutral
types in `app.llm.schemas` / `app.llm.exceptions`, so nothing else in the
application ever sees a Groq-specific object or exception.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import groq

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.schemas import (
    ChatMessage,
    ChatRole,
    CompletionResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolSpec,
)


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: groq.AsyncGroq | None = None

    def _get_client(self) -> groq.AsyncGroq:
        """Lazily builds the Groq client on first use.

        Deferred so importing/constructing the gateway never requires
        GROQ_API_KEY to be set (the app must start, and the test suite must
        pass, without one).
        """
        if self._client is None:
            api_key = (
                self._settings.groq_api_key.get_secret_value()
                if self._settings.groq_api_key
                else None
            )
            if not api_key:
                raise LLMAuthenticationError("GROQ_API_KEY is not configured", provider=self.name)
            self._client = groq.AsyncGroq(
                api_key=api_key,
                timeout=self._settings.llm_timeout_seconds,
                # The LLM gateway owns retry policy; disable the SDK's own.
                max_retries=0,
            )
        return self._client

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
        client = self._get_client()
        kwargs = _build_create_kwargs(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
        )
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _translate_exception(exc, provider=self.name) from exc

        return _to_completion_response(response, provider=self.name)

    async def stream_complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        kwargs = _build_create_kwargs(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for event in stream:
                yield _to_stream_chunk(event)
        except LLMError:
            raise
        except Exception as exc:
            raise _translate_exception(exc, provider=self.name) from exc


def _build_create_kwargs(
    *,
    model: str,
    messages: list[ChatMessage],
    temperature: float | None,
    max_tokens: int | None,
    response_format: dict[str, object] | None = None,
    tools: list[ToolSpec] | None = None,
    stream: bool | None = None,
    stream_options: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Omits unset parameters entirely, rather than sending explicit nulls."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [_message_to_groq_dict(message) for message in messages],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    if tools is not None:
        kwargs["tools"] = [_tool_spec_to_groq_dict(tool) for tool in tools]
    if stream is not None:
        kwargs["stream"] = stream
    if stream_options is not None:
        kwargs["stream_options"] = stream_options
    return kwargs


def _message_to_groq_dict(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.role == ChatRole.ASSISTANT and message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {"name": tool_call.name, "arguments": tool_call.arguments},
            }
            for tool_call in message.tool_calls
        ]
    if message.role == ChatRole.TOOL:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _tool_spec_to_groq_dict(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _usage_from(usage: Any) -> TokenUsage | None:
    if usage is None:
        return None
    return TokenUsage(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _request_id_from(response: Any) -> str | None:
    x_groq = getattr(response, "x_groq", None)
    if x_groq is not None:
        return x_groq.id
    return response.id


def _to_completion_response(response: Any, *, provider: str) -> CompletionResponse:
    choice = response.choices[0]
    return CompletionResponse(
        content=choice.message.content or "",
        model=response.model,
        provider=provider,
        finish_reason=choice.finish_reason,
        usage=_usage_from(response.usage) or TokenUsage(),
        request_id=_request_id_from(response),
        tool_calls=_tool_calls_from(choice.message),
    )


def _tool_calls_from(message: Any) -> list[ToolCall] | None:
    raw_tool_calls = getattr(message, "tool_calls", None)
    if not raw_tool_calls:
        return None
    return [
        ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
        for tc in raw_tool_calls
    ]


def _to_stream_chunk(event: Any) -> StreamChunk:
    choice = event.choices[0] if event.choices else None
    delta_content = choice.delta.content if choice and choice.delta else None
    finish_reason = choice.finish_reason if choice else None
    return StreamChunk(
        delta=delta_content or "",
        model=event.model,
        finish_reason=finish_reason,
        is_final=finish_reason is not None,
        usage=_usage_from(event.usage),
        request_id=_request_id_from(event),
    )


def _translate_exception(exc: Exception, *, provider: str) -> LLMError:
    # APITimeoutError subclasses APIConnectionError, and BadRequestError /
    # AuthenticationError / RateLimitError / etc. all subclass APIStatusError,
    # so the more specific checks must come first.
    if isinstance(exc, groq.APITimeoutError):
        return LLMTimeoutError("The request to the LLM provider timed out", provider=provider)
    if isinstance(exc, groq.RateLimitError):
        return LLMRateLimitError(
            "The LLM provider rate-limited this request",
            provider=provider,
            retry_after=_extract_retry_after(exc),
        )
    if isinstance(exc, groq.AuthenticationError | groq.PermissionDeniedError):
        return LLMAuthenticationError(
            "Authentication with the LLM provider failed", provider=provider
        )
    if isinstance(exc, groq.BadRequestError | groq.UnprocessableEntityError | groq.NotFoundError):
        return LLMInvalidRequestError(
            "The request to the LLM provider was invalid", provider=provider
        )
    if isinstance(exc, groq.APIConnectionError | groq.InternalServerError):
        return LLMProviderUnavailableError(
            "The LLM provider is temporarily unavailable", provider=provider
        )
    if isinstance(exc, groq.APIStatusError):
        return LLMProviderUnavailableError(
            "The LLM provider returned an unexpected error", provider=provider
        )
    return LLMProviderError("An unexpected LLM provider error occurred", provider=provider)


def _extract_retry_after(exc: groq.RateLimitError) -> float | None:
    headers = getattr(exc.response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
