"""Unit tests for the conversation endpoints.

The `ConversationService` dependency is overridden with a fake — no real
database is involved.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.domain.models.message import Message
from app.main import app
from app.services.conversation_service import ConversationService, get_conversation_service


class FakeConversationService(ConversationService):
    def __init__(
        self,
        *,
        conversations: list[Conversation] | None = None,
        detail: Conversation | None = None,
        deletable: bool = True,
    ) -> None:
        self._conversations = conversations or []
        self._detail = detail
        self._deletable = deletable

    async def list_conversations(self, *, limit: int = 50) -> list[Conversation]:
        return self._conversations[:limit]

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self._detail

    async def delete_conversation(self, conversation_id: uuid.UUID) -> bool:
        return self._deletable


def make_conversation(*, with_messages: bool = False) -> Conversation:
    now = datetime.now(UTC)
    conversation = Conversation(id=uuid.uuid4(), title="Test conversation")
    conversation.created_at = now
    conversation.updated_at = now
    if with_messages:
        conversation.messages = [
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content="hi",
                created_at=now,
            ),
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content="hello",
                model="openai/gpt-oss-120b",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                created_at=now,
            ),
        ]
    return conversation


@pytest.fixture
def override_conversation_service() -> Any:
    def _override(fake_service: ConversationService) -> None:
        app.dependency_overrides[get_conversation_service] = lambda: fake_service

    yield _override
    app.dependency_overrides.clear()


def test_list_conversations_returns_summaries(
    client: TestClient, override_conversation_service: Any
) -> None:
    conversation = make_conversation()
    override_conversation_service(FakeConversationService(conversations=[conversation]))

    response = client.get("/api/v1/conversations")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(conversation.id)
    assert body[0]["title"] == "Test conversation"
    assert "messages" not in body[0]


def test_get_conversation_returns_ordered_messages(
    client: TestClient, override_conversation_service: Any
) -> None:
    conversation = make_conversation(with_messages=True)
    override_conversation_service(FakeConversationService(detail=conversation))

    response = client.get(f"/api/v1/conversations/{conversation.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(conversation.id)
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["total_tokens"] == 2


def test_get_conversation_returns_404_when_missing(
    client: TestClient, override_conversation_service: Any
) -> None:
    override_conversation_service(FakeConversationService(detail=None))

    response = client.get(f"/api/v1/conversations/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"


def test_get_conversation_rejects_malformed_id(
    client: TestClient, override_conversation_service: Any
) -> None:
    override_conversation_service(FakeConversationService())

    response = client.get("/api/v1/conversations/not-a-uuid")

    assert response.status_code == 422


def test_delete_conversation_returns_204(
    client: TestClient, override_conversation_service: Any
) -> None:
    override_conversation_service(FakeConversationService(deletable=True))

    response = client.delete(f"/api/v1/conversations/{uuid.uuid4()}")

    assert response.status_code == 204


def test_delete_conversation_returns_404_when_missing(
    client: TestClient, override_conversation_service: Any
) -> None:
    override_conversation_service(FakeConversationService(deletable=False))

    response = client.delete(f"/api/v1/conversations/{uuid.uuid4()}")

    assert response.status_code == 404
