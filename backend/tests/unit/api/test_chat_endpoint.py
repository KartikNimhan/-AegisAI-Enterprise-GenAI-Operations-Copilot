"""Unit tests for the chat completion API endpoints.

The `ChatService` dependency is overridden with a fake — no real gateway,
provider, repository, or network call is involved.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError
from app.llm.schemas import CompletionResponse, ModelRole, StreamChunk, TokenUsage
from app.main import app
from app.services.chat_service import ChatService, ChatTurnResult, StreamTurnChunk, get_chat_service

_CONVERSATION_ID = uuid.uuid4()


class FakeChatService(ChatService):
    def __init__(
        self,
        *,
        response: CompletionResponse | None = None,
        stream_chunks: list[StreamChunk] | None = None,
        error: LLMError | None = None,
    ) -> None:
        self._response = response
        self._stream_chunks = stream_chunks or []
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def send_message(
        self, *, conversation_id: uuid.UUID | None, message: str, model_role: ModelRole
    ) -> ChatTurnResult:
        self.calls.append(
            {"conversation_id": conversation_id, "message": message, "model_role": model_role}
        )
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return ChatTurnResult(
            conversation_id=conversation_id or _CONVERSATION_ID, response=self._response
        )

    async def stream_message(
        self, *, conversation_id: uuid.UUID | None, message: str, model_role: ModelRole
    ) -> AsyncIterator[StreamTurnChunk]:
        self.calls.append(
            {"conversation_id": conversation_id, "message": message, "model_role": model_role}
        )
        if self._error is not None:
            raise self._error
        for chunk in self._stream_chunks:
            yield StreamTurnChunk(conversation_id=conversation_id or _CONVERSATION_ID, chunk=chunk)


@pytest.fixture
def override_chat_service() -> Iterator[Any]:
    def _override(fake_service: ChatService) -> None:
        app.dependency_overrides[get_chat_service] = lambda: fake_service

    yield _override
    app.dependency_overrides.clear()


def test_create_chat_completion_returns_normalized_response(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        response=CompletionResponse(
            content="hi there",
            model="openai/gpt-oss-120b",
            provider="groq",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3),
            request_id="req_1",
        )
    )
    override_chat_service(fake)

    response = client.post(
        "/api/v1/chat/completions", json={"message": "hello", "model_role": "primary"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "hi there"
    assert body["usage"]["total_tokens"] == 3
    assert body["conversation_id"] == str(_CONVERSATION_ID)
    assert fake.calls[0] == {
        "conversation_id": None,
        "message": "hello",
        "model_role": ModelRole.PRIMARY,
    }


def test_create_chat_completion_continues_existing_conversation(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        response=CompletionResponse(content="x", model="m", provider="groq", usage=TokenUsage())
    )
    override_chat_service(fake)
    existing_id = uuid.uuid4()

    client.post(
        "/api/v1/chat/completions",
        json={"conversation_id": str(existing_id), "message": "hello"},
    )

    assert fake.calls[0]["conversation_id"] == existing_id


def test_create_chat_completion_defaults_to_primary_role(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        response=CompletionResponse(content="x", model="m", provider="groq", usage=TokenUsage())
    )
    override_chat_service(fake)

    client.post("/api/v1/chat/completions", json={"message": "hello"})

    assert fake.calls[0]["model_role"] == ModelRole.PRIMARY


def test_create_chat_completion_rejects_empty_message(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        response=CompletionResponse(content="x", model="m", provider="groq", usage=TokenUsage())
    )
    override_chat_service(fake)

    response = client.post("/api/v1/chat/completions", json={"message": ""})

    assert response.status_code == 422


def test_create_chat_completion_rejects_invalid_model_role(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        response=CompletionResponse(content="x", model="m", provider="groq", usage=TokenUsage())
    )
    override_chat_service(fake)

    response = client.post(
        "/api/v1/chat/completions", json={"message": "hello", "model_role": "not-a-real-role"}
    )

    assert response.status_code == 422


def test_create_chat_completion_rejects_malformed_conversation_id(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        response=CompletionResponse(content="x", model="m", provider="groq", usage=TokenUsage())
    )
    override_chat_service(fake)

    response = client.post(
        "/api/v1/chat/completions",
        json={"conversation_id": "not-a-uuid", "message": "hello"},
    )

    assert response.status_code == 422


def test_create_chat_completion_rejects_malformed_json_body(client: TestClient) -> None:
    response = client.post("/api/v1/chat/completions", json={"model_role": "primary"})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (LLMRateLimitError("rate limited", provider="groq"), 429, "llm_rate_limited"),
        (LLMTimeoutError("timed out", provider="groq"), 504, "llm_timeout"),
    ],
)
def test_create_chat_completion_maps_llm_errors_to_http_status(
    client: TestClient,
    override_chat_service: Any,
    error: LLMError,
    expected_status: int,
    expected_code: str,
) -> None:
    override_chat_service(FakeChatService(error=error))

    response = client.post("/api/v1/chat/completions", json={"message": "hello"})

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_stream_chat_completion_emits_sse_events(
    client: TestClient, override_chat_service: Any
) -> None:
    fake = FakeChatService(
        stream_chunks=[
            StreamChunk(delta="He"),
            StreamChunk(delta="llo", finish_reason="stop", is_final=True),
        ]
    )
    override_chat_service(fake)

    with client.stream(
        "POST", "/api/v1/chat/completions/stream", json={"message": "hi"}
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "He" in body
    assert "llo" in body
    assert "[DONE]" in body
    assert str(_CONVERSATION_ID) in body


def test_stream_chat_completion_emits_error_event_on_failure(
    client: TestClient, override_chat_service: Any
) -> None:
    override_chat_service(FakeChatService(error=LLMTimeoutError("timed out", provider="groq")))

    with client.stream(
        "POST", "/api/v1/chat/completions/stream", json={"message": "hi"}
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "LLMTimeoutError" in body
