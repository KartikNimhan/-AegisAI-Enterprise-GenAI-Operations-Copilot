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
from app.services.citation_service import CitationService, CitationView, get_citation_service
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


class FakeCitationService(CitationService):
    """Serves pre-resolved citation views (the access checks themselves are tested in
    tests/unit/services/test_citation_service.py and the integration suite)."""

    def __init__(
        self,
        *,
        by_message: dict[uuid.UUID, list[CitationView]] | None = None,
        single: CitationView | Exception | None = None,
    ) -> None:
        self._by_message = by_message or {}
        self._single = single
        self.calls: list[dict[str, Any]] = []

    async def for_conversation(
        self, conversation_id: uuid.UUID
    ) -> dict[uuid.UUID, list[CitationView]]:
        return self._by_message

    async def get(self, **kwargs: Any) -> CitationView:
        self.calls.append(kwargs)
        if isinstance(self._single, Exception):
            raise self._single
        assert self._single is not None
        return self._single


@pytest.fixture
def override_citation_service() -> Any:
    def _override(fake: CitationService) -> None:
        app.dependency_overrides[get_citation_service] = lambda: fake

    yield _override
    app.dependency_overrides.pop(get_citation_service, None)


@pytest.fixture
def override_conversation_service() -> Any:
    def _override(fake_service: ConversationService) -> None:
        app.dependency_overrides[get_conversation_service] = lambda: fake_service
        # Conversation detail also lists citations; by default there are none (legacy).
        app.dependency_overrides.setdefault(get_citation_service, lambda: FakeCitationService())

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


# -- M10.4 T5/T6: citations ------------------------------------------------------------------------

_DOC = uuid.uuid4()
_CHUNK = uuid.uuid4()


def _available(message_id: uuid.UUID, source_id: str = "S1", **extra: Any) -> CitationView:
    return CitationView(
        message_id=message_id,
        source_id=source_id,
        position=int(source_id[1:]),
        cited=True,
        passage_truncated=False,
        available=True,
        document_id=_DOC,
        chunk_id=_CHUNK,
        filename="Travel Policy.pdf",
        chunk_index=3,
        page=2,
        similarity=0.8,
        passage="Employees may claim travel.",
        **extra,
    )


def _unavailable(message_id: uuid.UUID, source_id: str = "S2") -> CitationView:
    return CitationView(
        message_id=message_id,
        source_id=source_id,
        position=int(source_id[1:]),
        cited=False,
        passage_truncated=True,
        available=False,
    )


def test_a_legacy_conversation_lists_empty_citations(
    client: TestClient, override_conversation_service: Any
) -> None:
    conversation = make_conversation(with_messages=True)
    override_conversation_service(FakeConversationService(detail=conversation))

    body = client.get(f"/api/v1/conversations/{conversation.id}").json()

    assert [m["citations"] for m in body["messages"]] == [[], []]


def test_a_reopened_answer_lists_its_citations_without_leaking_unavailable_sources(
    client: TestClient, override_conversation_service: Any, override_citation_service: Any
) -> None:
    conversation = make_conversation(with_messages=True)
    answer = conversation.messages[1]
    override_citation_service(
        FakeCitationService(
            by_message={answer.id: [_available(answer.id), _unavailable(answer.id)]}
        )
    )
    override_conversation_service(FakeConversationService(detail=conversation))

    body = client.get(f"/api/v1/conversations/{conversation.id}").json()

    user, assistant = body["messages"]
    assert user["citations"] == []
    available, unavailable = assistant["citations"]
    assert available["status"] == "available"
    assert available["filename"] == "Travel Policy.pdf" and available["page"] == 2
    assert available["support"] == "not_verified"
    assert "passage" not in available and "text" not in available  # text only via the endpoint
    # The saved reference WAS truncated (`_unavailable` sets passage_truncated=True), but an
    # unavailable source reveals nothing about itself, not even that (M10 review finding L2).
    assert unavailable == {
        "source_id": "S2",
        "status": "unavailable",
        "cited": False,
        "passage_truncated": None,
        "support": "not_verified",
        "document_id": None,
        "chunk_id": None,
        "filename": None,
        "chunk_index": None,
        "page": None,
        "section": None,
    }


def _citation_url(conversation_id: uuid.UUID, message_id: uuid.UUID, source_id: str = "S1") -> str:
    return f"/api/v1/conversations/{conversation_id}/messages/{message_id}/citations/{source_id}"


def test_an_available_citation_returns_the_passage(
    client: TestClient, override_citation_service: Any
) -> None:
    conversation_id, message_id = uuid.uuid4(), uuid.uuid4()
    fake = FakeCitationService(single=_available(message_id))
    override_citation_service(fake)

    response = client.get(_citation_url(conversation_id, message_id))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["support"] == "not_verified"
    assert body["passage"] == {
        "text": "Employees may claim travel.",
        "characters": 27,
        "truncated": False,
    }
    assert body["neighbors"] is None  # not requested
    assert fake.calls == [
        {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "source_id": "S1",
            "neighbors": 0,
        }
    ]


def test_an_unavailable_citation_is_200_with_no_source_details(
    client: TestClient, override_citation_service: Any
) -> None:
    message_id = uuid.uuid4()
    override_citation_service(FakeCitationService(single=_unavailable(message_id, "S1")))

    response = client.get(_citation_url(uuid.uuid4(), message_id))

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "message_id": str(message_id),
        "source_id": "S1",
        "cited": False,
        "support": "not_verified",
    }


def test_neighbors_are_passed_through_and_returned(
    client: TestClient, override_citation_service: Any
) -> None:
    from app.services.citation_service import NeighborChunk

    message_id = uuid.uuid4()
    before = NeighborChunk(chunk_id=uuid.uuid4(), chunk_index=2, page=2, section=None, text="b")
    after = NeighborChunk(chunk_id=uuid.uuid4(), chunk_index=4, page=3, section=None, text="a")
    fake = FakeCitationService(
        single=_available(message_id, neighbors_before=(before,), neighbors_after=(after,))
    )
    override_citation_service(fake)

    body = client.get(_citation_url(uuid.uuid4(), message_id) + "?neighbors=2").json()

    assert fake.calls[0]["neighbors"] == 2
    assert [n["chunk_index"] for n in body["neighbors"]["before"]] == [2]
    assert [n["text"] for n in body["neighbors"]["after"]] == ["a"]


def test_a_citation_outside_the_callers_conversation_is_404(
    client: TestClient, override_citation_service: Any
) -> None:
    from app.core.exceptions import NotFoundError

    override_citation_service(FakeCitationService(single=NotFoundError("Citation not found")))

    response = client.get(_citation_url(uuid.uuid4(), uuid.uuid4()))

    assert response.status_code == 404


@pytest.mark.parametrize("source_id", ["S0", "S01", "S1000", "s1", "X1", "S1%20", "SOURCE1"])
def test_a_malformed_source_id_is_rejected_before_any_lookup(
    client: TestClient, override_citation_service: Any, source_id: str
) -> None:
    fake = FakeCitationService(single=_available(uuid.uuid4()))
    override_citation_service(fake)

    response = client.get(_citation_url(uuid.uuid4(), uuid.uuid4(), source_id))

    assert response.status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize("neighbors", ["-1", "3", "x"])
def test_neighbors_are_bounded_to_two(
    client: TestClient, override_citation_service: Any, neighbors: str
) -> None:
    fake = FakeCitationService(single=_available(uuid.uuid4()))
    override_citation_service(fake)

    response = client.get(_citation_url(uuid.uuid4(), uuid.uuid4()) + f"?neighbors={neighbors}")

    assert response.status_code == 422
    assert fake.calls == []
