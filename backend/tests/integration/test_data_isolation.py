"""Data isolation against a real PostgreSQL + pgvector database.

Five people, two organizations:

    alice  member of  Acme   (the default test user)         owns the data under test
    alan   member of  Acme   (a colleague)
    ada    ADMIN  of  Acme
    bob    member of  Other
    bea    ADMIN  of  Other

Every request goes through the real HTTP app, acting as one of them. The rules under test
(see app/auth/scope.py): conversations are private to their owner; documents are private to
their owner unless shared with the organization; an administrator may delete or re-share any
document in their organization but cannot read a private one; nothing ever crosses
organizations; and a resource the caller may not see is reported exactly like one that does
not exist. Retrieval and agent-tool paths are tested at the repository level with
deterministic vectors, so no embedding model or LLM is involved.

NOTE: written without a database available in the authoring environment, so these tests have
not been executed yet. They skip when Postgres is unreachable (see conftest.db_session).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.document_metadata import DocumentMetadataArgs, build_document_metadata_tool
from app.auth.scope import AccessScope
from app.core.exceptions import NotFoundError
from app.core.security import get_current_principal
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.db.session import get_session
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.enums.message_role import MessageRole
from app.domain.enums.user_role import UserRole
from app.domain.models.chunk_embedding import EMBEDDING_DIMENSION, ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.message import Message
from app.embeddings.providers.local import get_local_embedding_provider
from app.llm.gateway import get_llm_gateway
from app.llm.schemas import CompletionResponse, TokenUsage
from app.main import app
from app.rag.retrieval.repository import RetrievalRepository
from app.storage.local import LocalFileStorage, get_document_storage

from ..document_fixtures import make_txt_bytes
from ..unit.services.doubles import ScriptedChatGateway
from ..unit.services.embedding_doubles import FakeEmbeddingProvider
from .scoping import TestUser, create_user, owner_of

pytestmark = pytest.mark.integration


@dataclass
class World:
    alice: TestUser
    alan: TestUser
    ada: TestUser
    bob: TestUser
    bea: TestUser

    def everyone_but(self, *excluded: TestUser) -> list[TestUser]:
        return [
            u for u in (self.alice, self.alan, self.ada, self.bob, self.bea) if u not in excluded
        ]


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    alice = owner_of(db_session)
    other = await create_user(db_session)
    return World(
        alice=alice,
        alan=await create_user(db_session, organization_id=alice.organization_id),
        ada=await create_user(
            db_session, organization_id=alice.organization_id, role=UserRole.ADMIN
        ),
        bob=other,
        bea=await create_user(
            db_session, organization_id=other.organization_id, role=UserRole.ADMIN
        ),
    )


@pytest.fixture
async def client(db_session: AsyncSession, tmp_path: Path) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_document_storage] = lambda: LocalFileStorage(tmp_path / "uploads")
    app.dependency_overrides[get_local_embedding_provider] = lambda: FakeEmbeddingProvider(
        name="local", model_name="fake-model", model_version="1", dimension=EMBEDDING_DIMENSION
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http
    finally:
        for dependency in (get_session, get_document_storage, get_local_embedding_provider):
            app.dependency_overrides.pop(dependency, None)


def act_as(user: TestUser) -> None:
    """Subsequent requests are authenticated as this user (the db_session fixture restores the
    original override afterwards)."""
    app.dependency_overrides[get_current_principal] = lambda: user.principal


async def upload(
    client: AsyncClient, user: TestUser, content: bytes | None = None, name: str = "policy.txt"
) -> Response:
    act_as(user)
    return await client.post(
        "/api/v1/documents",
        files={"file": (name, content or make_txt_bytes(), "text/plain")},
    )


async def upload_id(client: AsyncClient, user: TestUser, content: bytes | None = None) -> str:
    response = await upload(client, user, content)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def error_of(response: Response) -> tuple[int, str, str]:
    """What a caller learns from a refusal, minus the per-request id."""
    error = response.json()["error"]
    return response.status_code, error["code"], error["message"]


async def as_user(
    client: AsyncClient, user: TestUser, method: str, url: str, **kwargs: Any
) -> Response:
    act_as(user)
    return await client.request(method, url, **kwargs)


# -- documents: read paths -----------------------------------------------------------


async def test_a_private_document_is_invisible_to_everyone_else(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)

    for stranger in world.everyone_but(world.alice):
        for path in ("", "/chunks", "/embeddings"):
            response = await as_user(
                client, stranger, "GET", f"/api/v1/documents/{document_id}{path}"
            )
            assert response.status_code == 404, (stranger.email, path, response.text)
        listing = await as_user(client, stranger, "GET", "/api/v1/documents")
        assert document_id not in [item["id"] for item in listing.json()["items"]]
        assert listing.json()["total"] == 0

    own = await as_user(client, world.alice, "GET", f"/api/v1/documents/{document_id}")
    assert own.status_code == 200 and own.json()["visibility"] == "private"


async def test_a_guessed_id_is_indistinguishable_from_a_foreign_one(
    client: AsyncClient, world: World
) -> None:
    foreign = await upload_id(client, world.alice)
    guessed = str(uuid.uuid4())

    for stranger in (world.alan, world.ada, world.bob, world.bea):
        for method, path, kwargs in (
            ("GET", "", {}),
            ("GET", "/chunks", {}),
            ("GET", "/embeddings", {}),
            ("POST", "/embeddings", {}),
            ("PATCH", "/visibility", {"json": {"visibility": "organization"}}),
        ):
            if stranger is world.ada and method == "PATCH":
                continue  # an administrator may re-share any document in their organization
            real = await as_user(
                client, stranger, method, f"/api/v1/documents/{foreign}{path}", **kwargs
            )
            fake = await as_user(
                client, stranger, method, f"/api/v1/documents/{guessed}{path}", **kwargs
            )
            assert error_of(real)[0] == 404
            assert error_of(real)[:2] == error_of(fake)[:2], (stranger.email, method, path)


# -- documents: sharing --------------------------------------------------------------


async def test_sharing_with_the_organization_makes_a_document_readable_there_only(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)

    shared = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )
    assert shared.status_code == 200 and shared.json()["visibility"] == "organization"

    for colleague in (world.alan, world.ada):
        for path in ("", "/chunks", "/embeddings"):
            response = await as_user(
                client, colleague, "GET", f"/api/v1/documents/{document_id}{path}"
            )
            assert response.status_code == 200, (colleague.email, path)
        listing = await as_user(client, colleague, "GET", "/api/v1/documents")
        assert document_id in [item["id"] for item in listing.json()["items"]]
    for outsider in (world.bob, world.bea):
        response = await as_user(client, outsider, "GET", f"/api/v1/documents/{document_id}")
        assert response.status_code == 404

    # Making it private again takes it back.
    await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "private"},
    )
    response = await as_user(client, world.alan, "GET", f"/api/v1/documents/{document_id}")
    assert response.status_code == 404


async def test_a_colleague_who_can_read_a_shared_document_cannot_change_or_delete_it(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)
    await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )

    patch = await as_user(
        client,
        world.alan,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "private"},
    )
    delete = await as_user(client, world.alan, "DELETE", f"/api/v1/documents/{document_id}")
    embed = await as_user(client, world.alan, "POST", f"/api/v1/documents/{document_id}/embeddings")

    assert (patch.status_code, delete.status_code, embed.status_code) == (404, 404, 404)
    still_there = await as_user(client, world.alice, "GET", f"/api/v1/documents/{document_id}")
    assert still_there.status_code == 200 and still_there.json()["visibility"] == "organization"


async def test_nobody_outside_the_organization_can_delete_or_share_a_document(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)

    for outsider in (world.bob, world.bea):
        delete = await as_user(client, outsider, "DELETE", f"/api/v1/documents/{document_id}")
        patch = await as_user(
            client,
            outsider,
            "PATCH",
            f"/api/v1/documents/{document_id}/visibility",
            json={"visibility": "organization"},
        )
        assert (delete.status_code, patch.status_code) == (404, 404), outsider.email

    assert (
        await as_user(client, world.alice, "GET", f"/api/v1/documents/{document_id}")
    ).status_code == 200


# -- documents: administrators -------------------------------------------------------


async def test_an_administrator_can_delete_a_members_private_document_without_reading_it(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alan)

    read = await as_user(client, world.ada, "GET", f"/api/v1/documents/{document_id}")
    delete = await as_user(client, world.ada, "DELETE", f"/api/v1/documents/{document_id}")
    afterwards = await as_user(client, world.alan, "GET", f"/api/v1/documents/{document_id}")

    assert read.status_code == 404  # administrators cannot read private documents
    assert delete.status_code == 204  # but may remove them
    assert afterwards.status_code == 404


async def test_an_administrator_of_another_organization_has_no_such_power(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alan)

    delete = await as_user(client, world.bea, "DELETE", f"/api/v1/documents/{document_id}")

    assert delete.status_code == 404
    assert (
        await as_user(client, world.alan, "GET", f"/api/v1/documents/{document_id}")
    ).status_code == 200


# -- documents: duplicate uploads ----------------------------------------------------


async def test_identical_uploads_by_different_people_never_merge_or_reveal_each_other(
    client: AsyncClient, world: World
) -> None:
    content = make_txt_bytes()
    first = await upload(client, world.alice, content)
    again = await upload(client, world.alice, content)
    colleague = await upload(client, world.alan, content)
    outsider = await upload(client, world.bob, content)

    assert first.status_code == 201
    assert again.status_code == 200 and again.json()["is_duplicate"] is True
    assert again.json()["id"] == first.json()["id"]  # your own re-upload is still a duplicate
    for other in (colleague, outsider):
        assert other.status_code == 201 and other.json()["is_duplicate"] is False
        assert other.json()["id"] != first.json()["id"]  # a new document of their own
    assert colleague.json()["id"] != outsider.json()["id"]


# -- conversations -------------------------------------------------------------------


async def _alice_conversation(db_session: AsyncSession, world: World) -> uuid.UUID:
    conversation = await ConversationRepository(db_session, world.alice.scope).create(
        title="private"
    )
    await MessageRepository(db_session, world.alice.scope).add(
        conversation_id=conversation.id, role=MessageRole.USER, content="alice's secret question"
    )
    await db_session.flush()
    return conversation.id


async def test_a_conversation_is_private_to_its_owner(
    client: AsyncClient, world: World, db_session: AsyncSession
) -> None:
    conversation_id = await _alice_conversation(db_session, world)

    for stranger in world.everyone_but(world.alice):
        read = await as_user(client, stranger, "GET", f"/api/v1/conversations/{conversation_id}")
        delete = await as_user(
            client, stranger, "DELETE", f"/api/v1/conversations/{conversation_id}"
        )
        listing = await as_user(client, stranger, "GET", "/api/v1/conversations")
        assert (read.status_code, delete.status_code) == (404, 404), stranger.email
        assert str(conversation_id) not in [c["id"] for c in listing.json()]

    own = await as_user(client, world.alice, "GET", f"/api/v1/conversations/{conversation_id}")
    assert own.status_code == 200
    assert [m["content"] for m in own.json()["messages"]] == ["alice's secret question"]


@pytest.mark.parametrize("path", ["/api/v1/chat/completions", "/api/v1/chat/completions/stream"])
async def test_nobody_can_continue_someone_elses_conversation_or_feed_it_to_the_model(
    client: AsyncClient, world: World, db_session: AsyncSession, path: str
) -> None:
    conversation_id = await _alice_conversation(db_session, world)
    gateway = ScriptedChatGateway()
    app.dependency_overrides[get_llm_gateway] = lambda: gateway
    try:
        for stranger in world.everyone_but(world.alice):
            response = await as_user(
                client,
                stranger,
                "POST",
                path,
                json={"conversation_id": str(conversation_id), "message": "what did alice ask?"},
            )
            assert response.status_code == 404, (stranger.email, response.text)
    finally:
        app.dependency_overrides.pop(get_llm_gateway, None)

    assert (
        gateway.chat_completion_calls == [] and gateway.stream_calls == []
    )  # the model never saw it
    messages = (
        (
            await db_session.execute(
                select(Message).where(Message.conversation_id == conversation_id)
            )
        )
        .scalars()
        .all()
    )
    assert [m.content for m in messages] == ["alice's secret question"]  # nothing was appended


async def test_the_owner_can_still_continue_their_own_conversation(
    client: AsyncClient, world: World, db_session: AsyncSession
) -> None:
    conversation_id = await _alice_conversation(db_session, world)
    gateway = ScriptedChatGateway(
        completion=CompletionResponse(
            content="Hello back",
            model="openai/gpt-oss-120b",
            provider="groq",
            finish_reason="stop",
            request_id="req_1",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
    )
    app.dependency_overrides[get_llm_gateway] = lambda: gateway
    try:
        response = await as_user(
            client,
            world.alice,
            "POST",
            "/api/v1/chat/completions",
            json={"conversation_id": str(conversation_id), "message": "and a follow-up"},
        )
    finally:
        app.dependency_overrides.pop(get_llm_gateway, None)

    assert response.status_code == 200
    assert len(gateway.chat_completion_calls) == 1


async def test_messages_are_reachable_only_through_the_owners_conversation(
    world: World, db_session: AsyncSession
) -> None:
    conversation_id = await _alice_conversation(db_session, world)

    assert (
        await MessageRepository(db_session, world.alan.scope).list_by_conversation(conversation_id)
        == []
    )
    with pytest.raises(NotFoundError):
        await MessageRepository(db_session, world.alan.scope).add(
            conversation_id=conversation_id, role=MessageRole.USER, content="injected"
        )
    assert (
        len(
            await MessageRepository(db_session, world.alice.scope).list_by_conversation(
                conversation_id
            )
        )
        == 1
    )


# -- retrieval, search and the agent tools -------------------------------------------


def _vector(*lead: float) -> list[float]:
    return [*lead, *([0.0] * (EMBEDDING_DIMENSION - len(lead)))]


async def _document_with_chunk(
    db_session: AsyncSession,
    owner: TestUser,
    vector: list[float],
    *,
    visibility: DocumentVisibility = DocumentVisibility.PRIVATE,
    text: str = "content",
) -> tuple[uuid.UUID, uuid.UUID]:
    document = DocumentRepository(db_session, owner.scope).new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="doc.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=10,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.PROCESSED,
        visibility=visibility,
    )
    await db_session.flush()
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=document.id,
        chunk_index=0,
        content=text,
        character_count=len(text),
    )
    db_session.add(chunk)
    await db_session.flush()
    db_session.add(
        ChunkEmbedding(
            id=uuid.uuid4(),
            document_chunk_id=chunk.id,
            embedding=vector,
            embedding_provider="local",
            embedding_model="fake-model",
            embedding_model_version="1",
            embedding_dimension=EMBEDDING_DIMENSION,
        )
    )
    await db_session.flush()
    return document.id, chunk.id


async def _search(
    db_session: AsyncSession, scope: AccessScope, query: list[float], **kwargs: Any
) -> list[uuid.UUID]:
    rows = await RetrievalRepository(db_session, scope).search(
        query_vector=query,
        model="fake-model",
        model_version="1",
        top_k=kwargs.pop("top_k", 5),
        **kwargs,
    )
    return [chunk.id for _, chunk, _, _ in rows]


async def test_retrieval_only_ever_returns_chunks_the_caller_may_read(
    world: World, db_session: AsyncSession
) -> None:
    query = _vector(1.0)  # identical to alice's chunk: the strongest possible match
    _, alice_chunk = await _document_with_chunk(db_session, world.alice, query)
    _, bob_chunk = await _document_with_chunk(db_session, world.bob, query)

    assert await _search(db_session, world.alice.scope, query) == [alice_chunk]
    assert await _search(db_session, world.bob.scope, query) == [bob_chunk]
    # A colleague, an administrator and another organization's people all get nothing of alice's.
    for stranger in (world.alan, world.ada, world.bob, world.bea):
        assert alice_chunk not in await _search(db_session, stranger.scope, query)


async def test_sharing_makes_a_documents_chunks_searchable_by_the_organization_only(
    world: World, db_session: AsyncSession
) -> None:
    query = _vector(1.0)
    document_id, chunk_id = await _document_with_chunk(
        db_session, world.alice, query, visibility=DocumentVisibility.ORGANIZATION
    )

    for colleague in (world.alan, world.ada):
        assert await _search(db_session, colleague.scope, query) == [chunk_id]
    for outsider in (world.bob, world.bea):
        assert await _search(db_session, outsider.scope, query) == []
        # naming the document explicitly does not help an outsider
        assert await _search(db_session, outsider.scope, query, document_id=document_id) == []


async def test_a_foreign_document_id_filter_narrows_to_nothing_rather_than_widening(
    world: World, db_session: AsyncSession
) -> None:
    query = _vector(1.0)
    alice_document, _ = await _document_with_chunk(db_session, world.alice, query)
    _, bob_chunk = await _document_with_chunk(db_session, world.bob, query)

    assert await _search(db_session, world.bob.scope, query, document_id=alice_document) == []
    assert await _search(db_session, world.bob.scope, query) == [bob_chunk]


async def test_other_peoples_chunks_cannot_crowd_out_your_own_results(
    world: World, db_session: AsyncSession
) -> None:
    """The scope is applied before the top-K limit: ten better matches belonging to someone else
    must not push the caller's own (worse) matches out of a top-3."""
    query = _vector(1.0)
    for _ in range(10):
        await _document_with_chunk(db_session, world.bob, _vector(1.0))  # a perfect match each
    mine = [
        (await _document_with_chunk(db_session, world.alice, _vector(0.1, 1.0)))[1]
        for _ in range(3)
    ]

    found = await _search(db_session, world.alice.scope, query, top_k=3)

    assert sorted(found) == sorted(mine)


async def test_the_embedding_search_and_counts_are_scoped_too(
    world: World, db_session: AsyncSession
) -> None:
    query = _vector(1.0)
    document_id, chunk_id = await _document_with_chunk(db_session, world.alice, query)

    own = ChunkEmbeddingRepository(db_session, world.alice.scope)
    other = ChunkEmbeddingRepository(db_session, world.bob.scope)

    assert [
        c.id
        for _, c, _ in await own.similarity_search(
            query_vector=query, model="fake-model", model_version="1"
        )
    ] == [chunk_id]
    assert (
        await other.similarity_search(query_vector=query, model="fake-model", model_version="1")
        == []
    )
    assert await own.count_for_document(document_id, model="fake-model", model_version="1") == 1
    assert await other.count_for_document(document_id, model="fake-model", model_version="1") == 0


async def test_the_agent_document_tool_cannot_see_foreign_documents(
    world: World, db_session: AsyncSession
) -> None:
    document_id, _ = await _document_with_chunk(db_session, world.alice, _vector(1.0))

    def tool_for(user: TestUser):
        return build_document_metadata_tool(DocumentRepository(db_session, user.scope)).executor

    own = await tool_for(world.alice)(DocumentMetadataArgs(document_id=document_id))
    assert own.success is True
    for stranger in (world.alan, world.ada, world.bob, world.bea):
        result = await tool_for(stranger)(DocumentMetadataArgs(document_id=document_id))
        assert result.success is False and result.error_code == "not_found", stranger.email


async def test_the_document_agent_endpoint_reports_foreign_documents_as_missing(
    client: AsyncClient, world: World
) -> None:
    document_id = await upload_id(client, world.alice)

    response = await as_user(
        client,
        world.bob,
        "POST",
        "/api/v1/agents/document/tasks",
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"text": str(document_id)}]}},
        },
    )

    # Whatever shape the A2A envelope takes, the other organization's document must not appear.
    assert "policy.txt" not in response.text


# -- operations summary --------------------------------------------------------------


async def test_the_document_status_counts_cover_only_what_the_caller_may_read(
    world: World, db_session: AsyncSession
) -> None:
    for _ in range(2):
        await _document_with_chunk(db_session, world.alice, _vector(1.0))
    await _document_with_chunk(
        db_session, world.alan, _vector(1.0), visibility=DocumentVisibility.ORGANIZATION
    )
    await _document_with_chunk(db_session, world.alan, _vector(1.0))  # private to alan
    await _document_with_chunk(db_session, world.bob, _vector(1.0))

    def counts(user: TestUser) -> Callable[[], Any]:
        return DocumentRepository(db_session, user.scope).count_by_status

    assert await counts(world.alice)() == {DocumentStatus.PROCESSED: 3}  # 2 own + alan's shared one
    assert await counts(world.alan)() == {
        DocumentStatus.PROCESSED: 2
    }  # 2 own (1 shared, 1 private)
    assert await counts(world.ada)() == {DocumentStatus.PROCESSED: 4}  # the whole organization
    assert await counts(world.bob)() == {DocumentStatus.PROCESSED: 1}
    assert await counts(world.bea)() == {DocumentStatus.PROCESSED: 1}  # Other's organization


# -- the administrator-only status page ----------------------------------------------


async def test_system_status_is_for_administrators_only(client: AsyncClient, world: World) -> None:
    for member in (world.alice, world.alan, world.bob):
        assert (await as_user(client, member, "GET", "/api/v1/system/status")).status_code == 403
    for admin in (world.ada, world.bea):
        assert (await as_user(client, admin, "GET", "/api/v1/system/status")).status_code == 200
