"""Unit tests for GroqProvider: response normalization and error translation.

No real network calls are made. The Groq client is replaced via
`GroqProvider._get_client` — the provider's own lazy-construction seam —
which is the correct boundary to mock: it isolates the SDK without
reaching into private httpx internals.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import groq
import httpx
import pytest
from groq.resources.chat.completions import AsyncCompletions
from pydantic import SecretStr

from app.config import Settings
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMOutputTruncatedError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.gateway import LLMGateway
from app.llm.providers.groq import GroqProvider
from app.llm.schemas import ChatMessage, ChatRole, ModelRole, ToolSpec

MESSAGES = [ChatMessage(role=ChatRole.USER, content="hello")]
_SDK_CREATE = inspect.signature(AsyncCompletions.create)


def assert_the_installed_sdk_accepts(kwargs: Mapping[str, Any]) -> None:
    """The fake client takes any argument, so bind what the provider sent to the installed SDK's
    real `create()` signature. An unknown keyword fails here, offline: `stream_options` once made
    every real stream raise a TypeError before any request was sent."""
    _SDK_CREATE.bind(None, **kwargs)


def sent_kwargs(create: AsyncMock) -> Mapping[str, Any]:
    assert create.await_args is not None, "create() was never called"
    return create.await_args.kwargs


def usage(prompt: int, completion: int, *, reasoning: int | None = None) -> SimpleNamespace:
    details = None if reasoning is None else SimpleNamespace(reasoning_tokens=reasoning)
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        completion_tokens_details=details,
    )


def stream_event(
    content: str,
    finish_reason: str | None = None,
    *,
    top_level_usage: SimpleNamespace | None = None,
    x_groq: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="chatcmpl_test",
        model="openai/gpt-oss-20b",
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)
        ],
        usage=top_level_usage,
        x_groq=x_groq,
    )


async def events(*items: SimpleNamespace) -> Any:
    for item in items:
        yield item


def make_provider(monkeypatch: pytest.MonkeyPatch, fake_client: Any) -> GroqProvider:
    settings = Settings(groq_api_key=SecretStr("dummy-test-key"))
    provider = GroqProvider(settings)
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)
    return provider


def make_client(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def fake_completion(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "id": "chatcmpl_test",
        "model": "openai/gpt-oss-120b",
        "choices": [
            SimpleNamespace(message=SimpleNamespace(content="hello back"), finish_reason="stop")
        ],
        "usage": SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        "x_groq": SimpleNamespace(id="req_abc"),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_api_status_error(
    cls: type[groq.APIStatusError],
    *,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
) -> groq.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resolved_status = status_code or getattr(cls, "status_code", 500)
    response = httpx.Response(status_code=resolved_status, request=request, headers=headers or {})
    return cls(message="boom", response=response, body=None)


async def test_complete_normalizes_successful_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(AsyncMock(return_value=fake_completion()))
    provider = make_provider(monkeypatch, client)

    result = await provider.complete(model="openai/gpt-oss-120b", messages=MESSAGES)

    assert result.content == "hello back"
    assert result.model == "openai/gpt-oss-120b"
    assert result.provider == "groq"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 15
    assert result.request_id == "req_abc"


async def test_complete_falls_back_to_completion_id_without_x_groq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(AsyncMock(return_value=fake_completion(x_groq=None)))
    provider = make_provider(monkeypatch, client)

    result = await provider.complete(model="openai/gpt-oss-120b", messages=MESSAGES)

    assert result.request_id == "chatcmpl_test"


async def collect_stream(provider: GroqProvider, **kwargs: Any) -> list[Any]:
    return [
        chunk
        async for chunk in provider.stream_complete(
            model="openai/gpt-oss-20b", messages=MESSAGES, **kwargs
        )
    ]


async def test_stream_complete_normalizes_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    # Groq's own contract: usage arrives on the final chunk's `x_groq.usage`, not top-level.
    stream = events(
        stream_event("He", x_groq=SimpleNamespace(id="req_abc")),
        stream_event("llo", "stop", x_groq=SimpleNamespace(id="req_abc", usage=usage(3, 2))),
    )
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=stream)))

    chunks = await collect_stream(provider)

    assert [c.delta for c in chunks] == ["He", "llo"]
    assert chunks[0].is_final is False
    assert chunks[0].usage is None
    assert chunks[1].is_final is True
    assert chunks[1].usage is not None
    assert chunks[1].usage.total_tokens == 5
    assert chunks[1].request_id == "req_abc"


async def test_stream_request_is_accepted_by_the_installed_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = AsyncMock(return_value=events(stream_event("hi", "stop")))
    provider = make_provider(monkeypatch, make_client(create))

    await collect_stream(provider, temperature=0.2, max_tokens=64)

    sent = sent_kwargs(create)
    assert sent["stream"] is True
    assert "stream_options" not in sent
    assert_the_installed_sdk_accepts(sent)


async def test_completion_request_is_accepted_by_the_installed_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = AsyncMock(return_value=fake_completion())
    provider = make_provider(monkeypatch, make_client(create))
    tool = ToolSpec(name="calculator", description="Adds numbers.", parameters={"type": "object"})

    await provider.complete(
        model="openai/gpt-oss-120b",
        messages=MESSAGES,
        temperature=0.2,
        max_tokens=64,
        response_format={"type": "json_object"},
        tools=[tool],
    )

    assert_the_installed_sdk_accepts(sent_kwargs(create))


async def test_stream_usage_falls_back_to_the_top_level_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = events(
        stream_event("hi", "stop", top_level_usage=usage(3, 2), x_groq=SimpleNamespace(id="r"))
    )
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=stream)))

    chunks = await collect_stream(provider)

    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 5


async def test_stream_prefers_x_groq_usage_over_the_top_level_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = events(
        stream_event(
            "hi",
            "stop",
            top_level_usage=usage(1, 1),
            x_groq=SimpleNamespace(id="r", usage=usage(3, 2)),
        )
    )
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=stream)))

    chunks = await collect_stream(provider)

    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 5


async def test_a_stream_without_any_usage_still_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = events(stream_event("He"), stream_event("llo", "stop", x_groq=None))
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=stream)))

    chunks = await collect_stream(provider)

    assert [c.delta for c in chunks] == ["He", "llo"]
    assert chunks[-1].is_final is True
    assert all(c.usage is None for c in chunks)


async def test_completion_counts_reasoning_tokens_within_output_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = fake_completion(usage=usage(10, 20, reasoning=18))
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=completion)))

    result = await provider.complete(model="openai/gpt-oss-20b", messages=MESSAGES)

    assert result.usage.output_tokens == 20  # reasoning is part of the output, never added to it
    assert result.usage.reasoning_tokens == 18
    assert result.usage.total_tokens == 30


async def test_completion_without_token_details_has_no_reasoning_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=fake_completion())))

    result = await provider.complete(model="openai/gpt-oss-120b", messages=MESSAGES)

    assert result.usage.output_tokens == 5
    assert result.usage.reasoning_tokens is None


async def test_reasoning_text_is_never_captured_and_its_count_is_never_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasoning_probe = "PRIVATE-REASONING-PROBE"
    completion = fake_completion(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="pong", reasoning=reasoning_probe),
                finish_reason="stop",
            )
        ],
        usage=usage(10, 9, reasoning=7),
    )
    provider = make_provider(monkeypatch, make_client(AsyncMock(return_value=completion)))

    result = await provider.complete(model="openai/gpt-oss-20b", messages=MESSAGES)

    assert result.content == "pong"
    assert reasoning_probe not in result.model_dump_json()
    assert result.usage.reasoning_tokens == 7
    # API responses and A2A payloads serialize `TokenUsage`; their shape is unchanged.
    assert result.usage.model_dump() == {"input_tokens": 10, "output_tokens": 9, "total_tokens": 19}
    assert "reasoning" not in result.usage.model_dump_json()


async def test_a_reasoning_only_reply_cut_off_by_the_limit_fails_once_through_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The first live run: HTTP 200, finish_reason "length", 20 output tokens, no content.
    completion = fake_completion(
        model="openai/gpt-oss-20b",
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="length")],
        usage=usage(80, 20, reasoning=20),
    )
    create = AsyncMock(return_value=completion)
    provider = make_provider(monkeypatch, make_client(create))
    gateway = LLMGateway(Settings(groq_api_key=SecretStr("dummy-test-key")), provider=provider)

    with pytest.raises(LLMOutputTruncatedError) as raised:
        await gateway.chat_completion(model_role=ModelRole.FAST, messages=MESSAGES, max_tokens=20)

    assert create.await_count == 1  # not retried: the same request would stop at the same limit
    assert raised.value.provider == "groq"
    assert raised.value.request_id == "req_abc"


@pytest.mark.parametrize(
    ("make_exc", "expected"),
    [
        (
            lambda: groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com")),
            LLMTimeoutError,
        ),
        (lambda: make_api_status_error(groq.RateLimitError), LLMRateLimitError),
        (lambda: make_api_status_error(groq.AuthenticationError), LLMAuthenticationError),
        (lambda: make_api_status_error(groq.PermissionDeniedError), LLMAuthenticationError),
        (lambda: make_api_status_error(groq.BadRequestError), LLMInvalidRequestError),
        (lambda: make_api_status_error(groq.NotFoundError), LLMInvalidRequestError),
        (lambda: make_api_status_error(groq.UnprocessableEntityError), LLMInvalidRequestError),
        (lambda: make_api_status_error(groq.InternalServerError), LLMProviderUnavailableError),
        (
            lambda: groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com")),
            LLMProviderUnavailableError,
        ),
        (lambda: ValueError("totally unexpected"), LLMProviderError),
    ],
)
async def test_complete_translates_exceptions(
    monkeypatch: pytest.MonkeyPatch, make_exc: Any, expected: type[Exception]
) -> None:
    client = make_client(AsyncMock(side_effect=make_exc()))
    provider = make_provider(monkeypatch, client)

    with pytest.raises(expected):
        await provider.complete(model="openai/gpt-oss-120b", messages=MESSAGES)


async def test_rate_limit_error_extracts_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(
        AsyncMock(
            side_effect=make_api_status_error(groq.RateLimitError, headers={"retry-after": "7"})
        )
    )
    provider = make_provider(monkeypatch, client)

    with pytest.raises(LLMRateLimitError) as exc_info:
        await provider.complete(model="openai/gpt-oss-120b", messages=MESSAGES)

    assert exc_info.value.retry_after == 7.0


def test_get_client_raises_authentication_error_without_api_key() -> None:
    provider = GroqProvider(Settings(groq_api_key=None))

    with pytest.raises(LLMAuthenticationError):
        provider._get_client()
