"""Unit tests for LLMGateway: role resolution, retries, errors, streaming.

Uses `ScriptedProvider` (no real Groq client/network call involved).
"""

from __future__ import annotations

import asyncio

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


async def test_excessive_retry_after_is_not_slept_on(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.llm.gateway.asyncio.sleep", record_sleep)
    provider = ScriptedProvider([LLMRateLimitError("slow down", retry_after=3600.0)])
    gateway = LLMGateway(make_settings(llm_max_retries=3), provider=provider)

    with pytest.raises(LLMRateLimitError):
        await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert slept == []
    assert len(provider.calls) == 1


async def test_reasonable_retry_after_is_still_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.llm.gateway.asyncio.sleep", record_sleep)
    ok = CompletionResponse(
        content="ok",
        model="m",
        provider="fake",
        finish_reason="stop",
        usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
    )
    provider = ScriptedProvider([LLMRateLimitError("wait", retry_after=10.0), ok])
    gateway = LLMGateway(make_settings(), provider=provider)

    await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert slept == [10.0]


async def test_unexpected_provider_exception_is_recorded_then_reraised() -> None:
    from app.observability import metrics

    metrics.reset(enabled=True)
    try:
        gateway = LLMGateway(
            make_settings(llm_max_retries=0),
            provider=ScriptedProvider([RuntimeError("raw sdk failure")]),
        )
        with pytest.raises(RuntimeError, match="raw sdk failure") as raised:
            await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)
        assert type(raised.value) is RuntimeError  # the original, not a wrapper
        text = metrics.render().decode()
        assert 'outcome="error"' in text
        assert 'error_type="other"' in text
    finally:
        metrics.reset(enabled=False)


class _SlowStream(ScriptedProvider):
    """Yields one chunk, then trickles forever (each gap far below any per-read timeout)."""

    def __init__(self) -> None:
        super().__init__([])
        self.closed = False

    async def stream_complete(self, **kwargs: object):
        try:
            yield StreamChunk(delta="first")
            while True:
                await asyncio.sleep(0.02)
                yield StreamChunk(delta=".")
        finally:
            self.closed = True


async def test_a_stream_that_never_finishes_hits_the_total_deadline() -> None:
    settings = make_settings()
    settings.llm_stream_total_timeout_seconds = 0.2
    provider = _SlowStream()
    gateway = LLMGateway(settings, provider=provider)
    received: list[str] = []

    with pytest.raises(LLMTimeoutError, match="exceeded"):
        async for chunk in gateway.stream_chat_completion(
            model_role=ModelRole.PRIMARY, messages=MESSAGES
        ):
            received.append(chunk.delta)

    assert received[0] == "first"
    assert provider.closed is True  # the provider stream was closed, not abandoned


async def test_a_stalled_stream_is_cut_off_by_the_deadline_not_just_the_chunk_gap() -> None:
    class Stalled(ScriptedProvider):
        async def stream_complete(self, **kwargs: object):
            yield StreamChunk(delta="a")
            await asyncio.sleep(30)
            yield StreamChunk(delta="never")

    settings = make_settings()
    settings.llm_stream_total_timeout_seconds = 0.2
    gateway = LLMGateway(settings, provider=Stalled([]))

    with pytest.raises(LLMTimeoutError):
        async for _ in gateway.stream_chat_completion(
            model_role=ModelRole.PRIMARY, messages=MESSAGES
        ):
            pass


async def test_a_normal_stream_is_unaffected_by_the_deadline() -> None:
    chunks = [StreamChunk(delta="a"), StreamChunk(delta="b", is_final=True)]
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([chunks]))

    got = [
        c.delta
        async for c in gateway.stream_chat_completion(
            model_role=ModelRole.PRIMARY, messages=MESSAGES
        )
    ]

    assert got == ["a", "b"]


def test_the_stream_deadline_is_validated() -> None:
    for bad in (0, -1, 100000):
        with pytest.raises(ValueError):
            make_settings_with(llm_stream_total_timeout_seconds=bad)


def make_settings_with(**overrides: object) -> Settings:
    return Settings(_env_file=None, debug=False, **overrides)  # type: ignore[call-arg,arg-type]
