"""Unit tests for GroqProvider: response normalization and error translation.

No real network calls are made. The Groq client is replaced via
`GroqProvider._get_client` — the provider's own lazy-construction seam —
which is the correct boundary to mock: it isolates the SDK without
reaching into private httpx internals.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import groq
import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers.groq import GroqProvider
from app.llm.schemas import ChatMessage, ChatRole

MESSAGES = [ChatMessage(role=ChatRole.USER, content="hello")]


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


async def test_stream_complete_normalizes_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream() -> Any:
        yield SimpleNamespace(
            id="chatcmpl_test",
            model="openai/gpt-oss-20b",
            choices=[SimpleNamespace(delta=SimpleNamespace(content="He"), finish_reason=None)],
            usage=None,
            x_groq=SimpleNamespace(id="req_abc"),
        )
        yield SimpleNamespace(
            id="chatcmpl_test",
            model="openai/gpt-oss-20b",
            choices=[SimpleNamespace(delta=SimpleNamespace(content="llo"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            x_groq=SimpleNamespace(id="req_abc"),
        )

    client = make_client(AsyncMock(return_value=fake_stream()))
    provider = make_provider(monkeypatch, client)

    chunks = [
        chunk
        async for chunk in provider.stream_complete(model="openai/gpt-oss-20b", messages=MESSAGES)
    ]

    assert [c.delta for c in chunks] == ["He", "llo"]
    assert chunks[0].is_final is False
    assert chunks[1].is_final is True
    assert chunks[1].usage is not None
    assert chunks[1].usage.total_tokens == 5


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
