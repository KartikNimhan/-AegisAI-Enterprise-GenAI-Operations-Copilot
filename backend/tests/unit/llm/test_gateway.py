"""Unit tests for LLMGateway: role resolution, retries, errors, streaming.

Uses `ScriptedProvider` (no real Groq client/network call involved).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.gateway import LLMGateway
from app.llm.schemas import (
    ChatMessage,
    ChatRole,
    CompletionResponse,
    ModelRole,
    StreamChunk,
    TokenUsage,
)

from .doubles import ScriptedProvider

MESSAGES = [ChatMessage(role=ChatRole.USER, content="hello")]


def make_settings(
    *,
    primary_llm_model: str = "openai/gpt-oss-120b",
    fast_llm_model: str = "openai/gpt-oss-20b",
    safety_llm_model: str = "openai/gpt-oss-safeguard-20b",
    llm_max_retries: int = 2,
    llm_timeout_seconds: float = 5.0,
) -> Settings:
    return Settings(
        primary_llm_model=primary_llm_model,
        fast_llm_model=fast_llm_model,
        safety_llm_model=safety_llm_model,
        llm_max_retries=llm_max_retries,
        llm_timeout_seconds=llm_timeout_seconds,
    )


def make_response(content: str = "hi") -> CompletionResponse:
    return CompletionResponse(
        content=content,
        model="openai/gpt-oss-120b",
        provider="fake",
        finish_reason="stop",
        usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        request_id="req_1",
    )


async def _fast_sleep(_seconds: float) -> None:
    return None


def test_resolve_model_maps_roles_to_configured_models() -> None:
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([]))

    assert gateway.resolve_model(ModelRole.PRIMARY) == "openai/gpt-oss-120b"
    assert gateway.resolve_model(ModelRole.FAST) == "openai/gpt-oss-20b"
    assert gateway.resolve_model(ModelRole.SAFETY) == "openai/gpt-oss-safeguard-20b"


def test_model_metadata_exposes_roles_and_provider() -> None:
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([]))

    assert gateway.model_metadata() == {
        "primary": "openai/gpt-oss-120b",
        "fast": "openai/gpt-oss-20b",
        "safety": "openai/gpt-oss-safeguard-20b",
        "provider": "fake",
    }


async def test_chat_completion_returns_normalized_response() -> None:
    provider = ScriptedProvider([make_response("hello back")])
    gateway = LLMGateway(make_settings(), provider=provider)

    result = await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert result.content == "hello back"
    assert provider.calls[0]["model"] == "openai/gpt-oss-120b"


async def test_retries_transient_errors_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.gateway.asyncio.sleep", _fast_sleep)
    provider = ScriptedProvider(
        [LLMTimeoutError("timed out", provider="fake"), make_response("ok")]
    )
    gateway = LLMGateway(make_settings(llm_max_retries=2), provider=provider)

    result = await gateway.chat_completion(model_role=ModelRole.FAST, messages=MESSAGES)

    assert result.content == "ok"
    assert len(provider.calls) == 2


async def test_exhausts_retries_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.gateway.asyncio.sleep", _fast_sleep)
    provider = ScriptedProvider(
        [
            LLMRateLimitError("rate limited", provider="fake"),
            LLMRateLimitError("rate limited", provider="fake"),
            LLMRateLimitError("rate limited", provider="fake"),
        ]
    )
    gateway = LLMGateway(make_settings(llm_max_retries=2), provider=provider)

    with pytest.raises(LLMRateLimitError):
        await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert len(provider.calls) == 3  # initial attempt + 2 retries


async def test_non_retryable_authentication_error_fails_immediately() -> None:
    provider = ScriptedProvider([LLMAuthenticationError("bad key", provider="fake")])
    gateway = LLMGateway(make_settings(llm_max_retries=2), provider=provider)

    with pytest.raises(LLMAuthenticationError):
        await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert len(provider.calls) == 1


async def test_non_retryable_invalid_request_error_fails_immediately() -> None:
    provider = ScriptedProvider([LLMInvalidRequestError("bad request", provider="fake")])
    gateway = LLMGateway(make_settings(llm_max_retries=2), provider=provider)

    with pytest.raises(LLMInvalidRequestError):
        await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert len(provider.calls) == 1


async def test_stream_chat_completion_yields_normalized_chunks() -> None:
    chunks = [
        StreamChunk(delta="He"),
        StreamChunk(delta="llo", finish_reason="stop", is_final=True),
    ]
    provider = ScriptedProvider([chunks])
    gateway = LLMGateway(make_settings(), provider=provider)

    received = [
        chunk
        async for chunk in gateway.stream_chat_completion(
            model_role=ModelRole.FAST, messages=MESSAGES
        )
    ]

    assert [c.delta for c in received] == ["He", "llo"]
    assert received[-1].is_final is True


async def test_stream_chat_completion_propagates_provider_error() -> None:
    provider = ScriptedProvider([LLMTimeoutError("timed out", provider="fake")])
    gateway = LLMGateway(make_settings(), provider=provider)

    with pytest.raises(LLMTimeoutError):
        async for _ in gateway.stream_chat_completion(model_role=ModelRole.FAST, messages=MESSAGES):
            pass
