"""M10.4 T7: saved citations against a real PostgreSQL database (tenant isolation, revocation,
deletion, manipulated references, neighbours, cascade).

Uses the five-person world of test_data_isolation.py (alice, alan and admin ada in Acme; bob and
admin bea in Other). Citations are saved through the real `CitationRepository` exactly as
`RAGService` saves them (records built from real chunks), then read through the real HTTP route.

STATUS: written offline, NOT RUN. These tests need the test database at migration 0009
(`tests/live_database.py` refuses a database behind the code's head), and applying migrations
needs the owner's approval (M10.4 database restrictions).
"""

# ruff: noqa: F811 -- the `world` and `client` fixtures are imported from test_data_isolation.py
# and requested by name, which pyflakes reads as a redefinition.

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.citation_repository import CitationRepository
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.message_repository import MessageRepository
from app.domain.enums.message_role import MessageRole
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.message_citation import MessageCitation
from app.rag.citation_records import CitationRecord
from app.rag.context.assembler import PASSAGE_RENDERING_VERSION, neutralize_markers, passage_sha256

from .scoping import TestUser
from .test_data_isolation import World, act_as, as_user, client, upload_id, world  # noqa: F401

pytestmark = pytest.mark.integration

LONG_TEXT = "\n\n".join(f"Section {i}. " + ("policy text " * 120) for i in range(6)).encode()


async def _chunks(session: AsyncSession, document_id: str) -> list[DocumentChunk]:
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == uuid.UUID(document_id))
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


def _record(chunk: DocumentChunk, source_id: str = "S1", **override: Any) -> CitationRecord:
    passage = neutralize_markers(chunk.content)
    fields: dict[str, Any] = {
        "source_id": source_id,
        "position": int(source_id[1:]),
        "document_id": chunk.document_id,
        "chunk_id": chunk.id,
        "similarity": 0.8,
        "cited": True,
        "passage_chars": len(passage),
        "passage_truncated": False,
        "rendering_version": PASSAGE_RENDERING_VERSION,
        "passage_sha256": passage_sha256(passage),
    }
    fields.update(override)
    return CitationRecord(**fields)


async def _answer_citing(
    session: AsyncSession, user: TestUser, records: list[CitationRecord]
) -> tuple[uuid.UUID, uuid.UUID]:
    conversation = await ConversationRepository(session, user.scope).create(title="cited")
    messages = MessageRepository(session, user.scope)
    await messages.add(conversation_id=conversation.id, role=MessageRole.USER, content="q")
    reply = await messages.add(
        conversation_id=conversation.id, role=MessageRole.ASSISTANT, content="a [S1]"
    )
    await CitationRepository(session, user.scope).add_for_message(
        message_id=reply.id, records=records
    )
    return conversation.id, reply.id


def _url(conversation_id: uuid.UUID, message_id: uuid.UUID, source_id: str = "S1") -> str:
    return f"/api/v1/conversations/{conversation_id}/messages/{message_id}/citations/{source_id}"


UNAVAILABLE_KEYS = {"status", "message_id", "source_id", "cited", "support"}


async def test_the_owner_reads_the_exact_passage(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(chunk)])

    response = await as_user(client, world.alice, "GET", _url(conversation_id, message_id))

    body = response.json()
    assert response.status_code == 200 and body["status"] == "available"
    assert body["passage"]["text"] == neutralize_markers(chunk.content)
    assert body["document_id"] == document_id and body["support"] == "not_verified"


@pytest.mark.parametrize("who", ["alan", "ada", "bob", "bea"])
async def test_nobody_else_can_read_a_citation_of_alices_conversation(
    db_session: AsyncSession, client: AsyncClient, world: World, who: str
) -> None:
    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(chunk)])

    response = await as_user(client, getattr(world, who), "GET", _url(conversation_id, message_id))

    assert response.status_code == 404  # exactly like a conversation that does not exist


async def test_revoked_access_makes_the_source_unavailable_without_details(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alan)
    shared = await as_user(
        client,
        world.alan,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )
    assert shared.status_code == 200
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(chunk)])
    before = await as_user(client, world.alice, "GET", _url(conversation_id, message_id))
    assert before.json()["status"] == "available"

    await as_user(
        client,
        world.alan,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "private"},
    )
    after = await as_user(client, world.alice, "GET", _url(conversation_id, message_id))

    assert after.status_code == 200
    assert after.json()["status"] == "unavailable"
    assert set(after.json()) == UNAVAILABLE_KEYS


async def test_a_deleted_document_leaves_the_reference_but_no_text(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(chunk)])

    deleted = await as_user(client, world.alice, "DELETE", f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 204
    response = await as_user(client, world.alice, "GET", _url(conversation_id, message_id))

    assert response.json()["status"] == "unavailable"
    assert set(response.json()) == UNAVAILABLE_KEYS
    kept = await db_session.scalar(
        select(func.count())
        .select_from(MessageCitation)
        .where(MessageCitation.message_id == message_id)
    )
    assert kept == 1  # decision 10: the reference is retained (subject to M9.5)


async def test_a_reference_to_another_tenants_chunk_never_reveals_it(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    """A manipulated row (no API can create it) pointing at bob's chunk is still unavailable."""
    bobs_document = await upload_id(client, world.bob)
    (bobs_chunk, *_) = await _chunks(db_session, bobs_document)
    conversation_id, message_id = await _answer_citing(
        db_session, world.alice, [_record(bobs_chunk)]
    )

    response = await as_user(client, world.alice, "GET", _url(conversation_id, message_id))

    assert response.json()["status"] == "unavailable"
    assert "policy" not in response.text.lower() and bobs_document not in response.text


async def test_a_tampered_hash_makes_the_source_unavailable(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(
        db_session, world.alice, [_record(chunk, passage_sha256="0" * 64)]
    )

    response = await as_user(client, world.alice, "GET", _url(conversation_id, message_id))

    assert response.json()["status"] == "unavailable"


async def test_neighbors_are_limited_to_two_and_to_the_same_readable_document(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice, LONG_TEXT)
    chunks = await _chunks(db_session, document_id)
    assert len(chunks) >= 5, "the long text must produce enough chunks"
    middle = chunks[len(chunks) // 2]
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(middle)])

    body = (
        await as_user(
            client, world.alice, "GET", _url(conversation_id, message_id) + "?neighbors=2"
        )
    ).json()

    assert [n["chunk_index"] for n in body["neighbors"]["before"]] == [
        middle.chunk_index - 2,
        middle.chunk_index - 1,
    ]
    assert [n["chunk_index"] for n in body["neighbors"]["after"]] == [
        middle.chunk_index + 1,
        middle.chunk_index + 2,
    ]
    too_many = await as_user(
        client, world.alice, "GET", _url(conversation_id, message_id) + "?neighbors=3"
    )
    assert too_many.status_code == 422


async def test_a_reopened_conversation_lists_its_citations_and_old_messages_list_none(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(chunk)])

    body = (
        await as_user(client, world.alice, "GET", f"/api/v1/conversations/{conversation_id}")
    ).json()

    user_message, answer = body["messages"]
    assert user_message["citations"] == []
    (summary,) = answer["citations"]
    assert summary["status"] == "available" and summary["document_id"] == document_id
    assert "passage" not in summary


async def test_deleting_the_conversation_deletes_its_citations(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    conversation_id, message_id = await _answer_citing(db_session, world.alice, [_record(chunk)])

    deleted = await as_user(
        client, world.alice, "DELETE", f"/api/v1/conversations/{conversation_id}"
    )

    assert deleted.status_code == 204
    left = await db_session.scalar(
        select(func.count())
        .select_from(MessageCitation)
        .where(MessageCitation.message_id == message_id)
    )
    assert left == 0  # ON DELETE CASCADE through messages


async def test_citations_cannot_be_saved_for_someone_elses_message(
    db_session: AsyncSession, client: AsyncClient, world: World
) -> None:
    from app.core.exceptions import NotFoundError

    document_id = await upload_id(client, world.alice)
    (chunk, *_) = await _chunks(db_session, document_id)
    _conversation_id, message_id = await _answer_citing(db_session, world.alice, [])

    with pytest.raises(NotFoundError):
        await CitationRepository(db_session, world.bob.scope).add_for_message(
            message_id=message_id, records=[_record(chunk)]
        )
