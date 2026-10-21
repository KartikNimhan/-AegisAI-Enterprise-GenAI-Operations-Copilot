"""Every business repository query is built with the caller's access scope.

A recording session captures the SQL each repository method sends; the tests compile it for
PostgreSQL and require the caller's ids to be bound into every statement. The rules those
predicates implement are proven separately (test_access_scope.py, executed as real SQL), and
against a real database in tests/integration/test_data_isolation.py. This file is the guard
that no repository method is ever added or edited without applying them.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.auth.scope import AccessScope
from app.core.exceptions import NotFoundError
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.enums.message_role import MessageRole
from app.rag.retrieval.repository import RetrievalRepository

USER, ORG = uuid.uuid4(), uuid.uuid4()
MEMBER = AccessScope.for_user(user_id=USER, organization_id=ORG)
ADMIN = AccessScope.for_user(user_id=uuid.uuid4(), organization_id=ORG, is_admin=True)
SOME_ID = uuid.uuid4()
VECTOR = [0.1] * 384


class _Result:
    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> _Result:
        return self

    def first(self) -> None:
        return None

    def all(self) -> list[Any]:
        return []


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result()

    async def scalar(self, statement: Any) -> None:
        self.statements.append(statement)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: Any) -> None:
        self.added.extend(objs)

    async def flush(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        return None


def _bound_values(statement: Any) -> list[Any]:
    return list(statement.compile(dialect=postgresql.dialect()).params.values())


def _assert_every_statement_binds(session: RecordingSession, *expected: uuid.UUID) -> None:
    assert session.statements, "the method issued no query"
    for statement in session.statements:
        values = _bound_values(statement)
        for wanted in expected:
            assert wanted in values, f"a statement is not scoped to {wanted}:\n{statement}"


# -- documents ----------------------------------------------------------------------

DOCUMENT_CALLS = {
    "get": lambda r: r.get(SOME_ID),
    "get_for_management": lambda r: r.get_for_management(SOME_ID),
    "get_by_checksum": lambda r: r.get_by_checksum("a" * 64),
    "list": lambda r: r.list(),
    "count_by_status": lambda r: r.count_by_status(),
    "delete": lambda r: r.delete(SOME_ID),
    "set_visibility": lambda r: r.set_visibility(SOME_ID, DocumentVisibility.ORGANIZATION),
}


@pytest.mark.parametrize("name", DOCUMENT_CALLS)
async def test_every_document_query_is_scoped_to_the_callers_user_and_organization(
    name: str,
) -> None:
    session = RecordingSession()
    await DOCUMENT_CALLS[name](DocumentRepository(session, MEMBER))  # type: ignore[arg-type]

    if name == "get_by_checksum":
        # Duplicate detection is by owner only.
        _assert_every_statement_binds(session, USER)
    else:
        _assert_every_statement_binds(session, USER, ORG)


@pytest.mark.parametrize("name", ["get_for_management", "delete", "set_visibility"])
async def test_an_administrators_management_queries_are_scoped_to_their_organization(
    name: str,
) -> None:
    session = RecordingSession()
    await DOCUMENT_CALLS[name](DocumentRepository(session, ADMIN))  # type: ignore[arg-type]

    _assert_every_statement_binds(session, ORG)


async def test_an_administrators_summary_is_scoped_to_their_organization_only() -> None:
    session = RecordingSession()

    await DocumentRepository(session, ADMIN).count_by_status()  # type: ignore[arg-type]

    values = _bound_values(session.statements[0])
    assert ORG in values
    assert ADMIN.user_id not in values  # counts the organization, not just the admin's own


async def test_an_administrators_read_queries_are_still_the_ordinary_read_scope() -> None:
    session = RecordingSession()
    admin_repo = DocumentRepository(session, ADMIN)  # type: ignore[arg-type]

    await admin_repo.get(SOME_ID)
    await admin_repo.list()

    _assert_every_statement_binds(session, ADMIN.user_id, ORG)  # type: ignore[arg-type]


def test_a_new_document_is_owned_by_the_caller_and_cannot_be_given_to_someone_else() -> None:
    session = RecordingSession()
    repo = DocumentRepository(session, MEMBER)  # type: ignore[arg-type]

    document = repo.new(filename="k", original_filename="a.txt")
    assert document.owner_user_id == USER and document.organization_id == ORG

    with pytest.raises(ValueError, match="access scope"):
        repo.new(filename="k", owner_user_id=uuid.uuid4())
    with pytest.raises(ValueError, match="access scope"):
        repo.new(filename="k", organization_id=uuid.uuid4())


def test_a_document_cannot_be_created_without_an_owner() -> None:
    nobody = AccessScope(user_id=None, organization_id=None)
    with pytest.raises(ValueError, match="needs an owner"):
        DocumentRepository(RecordingSession(), nobody).new(filename="k")  # type: ignore[arg-type]


def test_only_an_operator_scope_may_name_the_owner_of_a_new_document() -> None:
    repo = DocumentRepository(RecordingSession(), AccessScope.unrestricted_for_operators())  # type: ignore[arg-type]
    owner = uuid.uuid4()

    document = repo.new(filename="k", owner_user_id=owner, organization_id=ORG)

    assert document.owner_user_id == owner


# -- conversations and messages -----------------------------------------------------

CONVERSATION_CALLS = {
    "get": lambda r: r.get(SOME_ID),
    "get_with_messages": lambda r: r.get_with_messages(SOME_ID),
    "list": lambda r: r.list(),
    "delete": lambda r: r.delete(SOME_ID),
}


@pytest.mark.parametrize("name", CONVERSATION_CALLS)
async def test_every_conversation_query_is_scoped_to_the_owner(name: str) -> None:
    session = RecordingSession()
    await CONVERSATION_CALLS[name](ConversationRepository(session, MEMBER))  # type: ignore[arg-type]

    _assert_every_statement_binds(session, USER)


async def test_an_administrator_gets_no_special_access_to_conversations() -> None:
    session = RecordingSession()
    repo = ConversationRepository(session, ADMIN)  # type: ignore[arg-type]

    await repo.get(SOME_ID)
    await repo.list()

    _assert_every_statement_binds(session, ADMIN.user_id)  # type: ignore[arg-type]


async def test_a_new_conversation_is_owned_by_the_caller_and_cannot_be_given_to_someone_else() -> (
    None
):
    session = RecordingSession()
    repo = ConversationRepository(session, MEMBER)  # type: ignore[arg-type]

    conversation = await repo.create(title="hi")
    assert conversation.owner_user_id == USER and conversation.organization_id == ORG

    with pytest.raises(ValueError, match="access scope"):
        await repo.create(owner_user_id=uuid.uuid4())


async def test_listing_messages_goes_through_the_callers_conversation() -> None:
    session = RecordingSession()

    await MessageRepository(session, MEMBER).list_by_conversation(SOME_ID)  # type: ignore[arg-type]

    _assert_every_statement_binds(session, USER)


async def test_a_message_cannot_be_added_to_a_conversation_the_caller_does_not_own() -> None:
    session = RecordingSession()  # every lookup finds nothing: the conversation is not visible

    with pytest.raises(NotFoundError):
        await MessageRepository(session, MEMBER).add(  # type: ignore[arg-type]
            conversation_id=SOME_ID, role=MessageRole.USER, content="injected"
        )

    assert session.added == []  # nothing was written
    _assert_every_statement_binds(session, USER)


# -- chunks, embeddings and retrieval -----------------------------------------------


async def test_chunk_reads_go_through_a_document_the_caller_may_read() -> None:
    session = RecordingSession()
    repo = DocumentChunkRepository(session, MEMBER)  # type: ignore[arg-type]

    await repo.list_by_document(SOME_ID)
    await repo.count_by_document(SOME_ID)

    _assert_every_statement_binds(session, USER, ORG)


async def test_embedding_reads_go_through_a_document_the_caller_may_read() -> None:
    session = RecordingSession()
    repo = ChunkEmbeddingRepository(session, MEMBER)  # type: ignore[arg-type]

    await repo.similarity_search(query_vector=VECTOR, model="m", model_version="1", top_k=5)
    await repo.count_for_document(SOME_ID, model="m", model_version="1")

    _assert_every_statement_binds(session, USER, ORG)


@pytest.mark.parametrize("document_id", [None, SOME_ID])
async def test_rag_retrieval_ranks_only_documents_the_caller_may_read(
    document_id: uuid.UUID | None,
) -> None:
    session = RecordingSession()

    await RetrievalRepository(session, MEMBER).search(  # type: ignore[arg-type]
        query_vector=VECTOR, model="m", model_version="1", top_k=3, document_id=document_id
    )

    # With or without a caller-supplied document_id, the scope is applied: that id can narrow
    # the search but never widen it.
    _assert_every_statement_binds(session, USER, ORG)


async def test_the_scope_is_applied_before_the_top_k_limit() -> None:
    """If the scope were applied after LIMIT, another owner's chunks could fill the top-K and
    crowd out the caller's own results (or leak through their presence)."""
    session = RecordingSession()

    await RetrievalRepository(session, MEMBER).search(  # type: ignore[arg-type]
        query_vector=VECTOR, model="m", model_version="1", top_k=3
    )

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert sql.index("documents.organization_id") < sql.index("LIMIT")
    assert sql.index("documents.owner_user_id") < sql.index("ORDER BY")
