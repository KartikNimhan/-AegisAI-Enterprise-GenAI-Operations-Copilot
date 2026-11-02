"""LLM requests, errors, retries, latency and token usage, measured in `LLMGateway`.

Uses the scripted provider from the gateway tests (no network, no real SDK).
"""

from __future__ import annotations

import pytest

from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMProviderUnavailableError,
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
from app.observability import metrics

from ..llm.doubles import ScriptedProvider
from ..llm.test_gateway import make_settings
from .helpers import exposition, samples, value

MESSAGES = [ChatMessage(role=ChatRole.USER, content="hello")]


def response(usage: TokenUsage | None = None) -> CompletionResponse:
    return CompletionResponse(
        content="hi",
        model="m",
        provider="fake",
        finish_reason="stop",
        usage=usage if usage is not None else TokenUsage(),
        request_id="req_1",
    )


async def no_sleep(_seconds: float) -> None:
    return None


async def collect(gateway: LLMGateway, role: ModelRole = ModelRole.PRIMARY) -> list[StreamChunk]:
    return [c async for c in gateway.stream_chat_completion(model_role=role, messages=MESSAGES)]


# -- chat_completion -----------------------------------------------------------------------


async def test_a_successful_call_records_outcome_latency_and_tokens() -> None:
    usage = TokenUsage(input_tokens=11, output_tokens=5, total_tokens=16)
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([response(usage)]))

    result = await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert result.usage == usage  # the caller still gets the provider's response untouched
    requests = {"provider": "fake", "model_role": "primary", "operation": "chat_completion"}
    assert value("aegis_llm_requests_total", outcome="success", **requests) == 1
    assert value("aegis_llm_requests_total", outcome="error") == 0
    assert value("aegis_llm_request_duration_seconds_count", provider="fake") == 1
    assert value("aegis_llm_tokens_total", direction="input", model_role="primary") == 11
    assert value("aegis_llm_tokens_total", direction="output", model_role="primary") == 5


async def test_the_model_role_label_is_the_role_not_the_model_name() -> None:
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([response()]))

    await gateway.chat_completion(model_role=ModelRole.FAST, messages=MESSAGES)

    assert value("aegis_llm_requests_total", model_role="fast") == 1
    assert "gpt-oss" not in exposition()


async def test_missing_usage_adds_no_tokens_and_does_not_fail_the_call() -> None:
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([response(TokenUsage())]))

    await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert value("aegis_llm_requests_total", outcome="success") == 1
    assert value("aegis_llm_tokens_total") == 0


async def test_a_retried_call_counts_each_retry_once_and_one_final_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.llm.gateway.asyncio.sleep", no_sleep)
    provider = ScriptedProvider(
        [LLMTimeoutError("t", provider="fake"), LLMRateLimitError("r", provider="fake"), response()]
    )
    gateway = LLMGateway(make_settings(llm_max_retries=2), provider=provider)

    await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert value("aegis_llm_retries_total", error_type="LLMTimeoutError") == 1
    assert value("aegis_llm_retries_total", error_type="LLMRateLimitError") == 1
    assert value("aegis_llm_requests_total", outcome="success") == 1
    assert value("aegis_llm_requests_total", outcome="error") == 0
    assert value("aegis_llm_errors_total") == 0  # retried errors that recovered are not failures
    assert value("aegis_llm_request_duration_seconds_count", provider="fake") == 3  # 3 attempts


async def test_exhausted_retries_are_one_failed_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.gateway.asyncio.sleep", no_sleep)
    errors = [LLMProviderUnavailableError("down", provider="fake") for _ in range(3)]
    gateway = LLMGateway(make_settings(llm_max_retries=2), provider=ScriptedProvider(errors))

    with pytest.raises(LLMProviderUnavailableError):
        await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert value("aegis_llm_requests_total", outcome="error", operation="chat_completion") == 1
    assert value("aegis_llm_errors_total", error_type="LLMProviderUnavailableError") == 1
    assert value("aegis_llm_retries_total", error_type="LLMProviderUnavailableError") == 2
    assert value("aegis_llm_tokens_total") == 0


async def test_a_non_retryable_error_is_a_failure_without_retries() -> None:
    gateway = LLMGateway(
        make_settings(),
        provider=ScriptedProvider([LLMAuthenticationError("bad key", provider="fake")]),
    )

    with pytest.raises(LLMAuthenticationError):
        await gateway.chat_completion(model_role=ModelRole.SAFETY, messages=MESSAGES)

    assert value("aegis_llm_errors_total", error_type="LLMAuthenticationError") == 1
    assert value("aegis_llm_retries_total") == 0
    assert value("aegis_llm_requests_total", model_role="safety", outcome="error") == 1


async def test_error_messages_and_prompts_never_reach_the_metrics() -> None:
    secret_text = "the user's private prompt and an internal stack detail"
    gateway = LLMGateway(
        make_settings(),
        provider=ScriptedProvider([LLMAuthenticationError(secret_text, provider="fake")]),
    )

    with pytest.raises(LLMAuthenticationError):
        await gateway.chat_completion(
            model_role=ModelRole.PRIMARY,
            messages=[ChatMessage(role=ChatRole.USER, content="private prompt hello")],
        )

    text = exposition()
    assert secret_text not in text and "private" not in text and "hello" not in text


async def test_an_unknown_provider_error_class_is_reported_as_other() -> None:
    class StrangeLLMError(LLMAuthenticationError):
        pass

    gateway = LLMGateway(
        make_settings(), provider=ScriptedProvider([StrangeLLMError("x", provider="fake")])
    )

    with pytest.raises(StrangeLLMError):
        await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert value("aegis_llm_errors_total", error_type="other") == 1
    assert "StrangeLLMError" not in exposition()


async def test_disabled_metrics_record_nothing_and_change_nothing() -> None:
    metrics.reset(enabled=False)
    usage = TokenUsage(input_tokens=2, output_tokens=2, total_tokens=4)
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([response(usage)]))

    result = await gateway.chat_completion(model_role=ModelRole.PRIMARY, messages=MESSAGES)

    assert result.usage == usage
    assert samples() == []  # no samples (the registry's HELP/TYPE header lines are not data)


# -- streaming ---------------------------------------------------------------------------------


def chunks_with_usage() -> list[StreamChunk]:
    return [
        StreamChunk(delta="Hel"),
        StreamChunk(delta="lo"),
        StreamChunk(
            delta="",
            is_final=True,
            finish_reason="stop",
            usage=TokenUsage(input_tokens=20, output_tokens=8, total_tokens=28),
        ),
    ]


async def test_stream_usage_on_the_final_chunk_is_recorded_without_changing_the_stream() -> None:
    expected = chunks_with_usage()
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([expected]))

    received = await collect(gateway, ModelRole.FAST)

    assert received == expected  # same chunks, same order, nothing added or dropped
    assert value("aegis_llm_tokens_total", direction="input", model_role="fast") == 20
    assert value("aegis_llm_tokens_total", direction="output", model_role="fast") == 8
    stream = {"operation": "stream_chat_completion", "provider": "fake"}
    assert value("aegis_llm_requests_total", outcome="success", **stream) == 1
    assert value("aegis_llm_request_duration_seconds_count", **stream) == 1


async def test_stream_usage_repeated_on_several_chunks_is_counted_once() -> None:
    usage = TokenUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    chunks = [
        StreamChunk(delta="a", usage=usage),
        StreamChunk(delta="b", usage=usage, is_final=True),
    ]
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([chunks]))

    await collect(gateway)

    assert value("aegis_llm_tokens_total", direction="input") == 3


async def test_a_stream_without_usage_adds_no_tokens() -> None:
    chunks = [StreamChunk(delta="a"), StreamChunk(delta="", is_final=True)]
    gateway = LLMGateway(make_settings(), provider=ScriptedProvider([chunks]))

    received = await collect(gateway)

    assert received == chunks
    assert value("aegis_llm_tokens_total") == 0
    assert value("aegis_llm_requests_total", outcome="success") == 1


async def test_a_failing_stream_is_counted_as_an_error_and_still_raises() -> None:
    gateway = LLMGateway(
        make_settings(), provider=ScriptedProvider([LLMTimeoutError("slow", provider="fake")])
    )

    with pytest.raises(LLMTimeoutError):
        await collect(gateway)

    assert (
        value("aegis_llm_requests_total", outcome="error", operation="stream_chat_completion") == 1
    )
    assert value("aegis_llm_errors_total", error_type="LLMTimeoutError") == 1
    assert value("aegis_llm_retries_total") == 0  # streams are never retried
