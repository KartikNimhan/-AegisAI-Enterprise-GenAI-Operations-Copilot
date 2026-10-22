"""M5: metadata filters (request validation, plumbing, SQL) and citation validation in RAGService.

All offline: fakes for retrieval and the model, and compiled SQL for the repository. The database
twin for filters and cross-user access is tests/integration/test_rag_filters.py (not run here).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.schemas.rag import RAGChatRequest
from app.auth.scope import AccessScope
from app.domain.enums.document_type import DocumentType
from app.llm.schemas import ModelRole, StreamChunk
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.schemas import RetrievalFilters
from app.rag.service import NO_CONTEXT_RESPONSE

from .doubles import FakeRetrievalStrategy, ScriptedRAGGateway, make_result
from .test_rag_service import make_completion, make_service

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 6, 1, tzinfo=UTC)


# -- request validation ------------------------------------------------------------


def test_request_accepts_the_supported_filters() -> None:
    request = RAGChatRequest(
        message="q",
        document_types=["pdf", "txt"],  # type: ignore[list-item]
        filename="policy.pdf",
        created_after=T0,
        created_before=T1,
    )

    filters = request.to_filters()

    assert filters.document_types == frozenset({DocumentType.PDF, DocumentType.TXT})
    assert filters.filename == "policy.pdf"
    assert (filters.created_after, filters.created_before) == (T0, T1)


@pytest.mark.parametrize(
    "extra",
    [
        {"document_types": ["exe"]},
        {"document_types": []},
        {"filename": ""},
        {"filename": "x" * 256},
        {"created_after": "2026-01-01T00:00:00"},  # no timezone
        {"created_after": "2026-06-01T00:00:00Z", "created_before": "2026-01-01T00:00:00Z"},
        {"document_id": "not-a-uuid"},
    ],
)
def test_invalid_filters_are_rejected(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RAGChatRequest(message="q", **extra)


def test_unknown_request_fields_cannot_smuggle_a_scope_override() -> None:
    request = RAGChatRequest.model_validate(
        {"message": "q", "owner_user_id": str(uuid.uuid4()), "organization_id": str(uuid.uuid4())}
    )

    assert not hasattr(request, "owner_user_id")
    assert request.to_filters().is_empty


def test_no_filters_means_an_empty_filter_set() -> None:
    assert RAGChatRequest(message="q").to_filters().is_empty


# -- plumbing ----------------------------------------------------------------------


async def test_filters_reach_the_retrieval_strategy_and_the_response_metadata() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result()])
    service, *_ = make_service(
        gateway=ScriptedRAGGateway(completion=make_completion()), strategy=strategy
    )
    filters = RetrievalFilters(document_types=frozenset({DocumentType.PDF}), created_after=T0)

    answer = await service.answer(
        conversation_id=None, message="q", model_role=ModelRole.PRIMARY, filters=filters
    )

    assert strategy.calls[0]["filters"] == filters
    assert answer.retrieval.filters == {"document_types": ["pdf"], "created_after": T0.isoformat()}


async def test_document_id_and_other_filters_combine() -> None:
    document_id = uuid.uuid4()
    strategy = FakeRetrievalStrategy(results=[make_result()])
    service, *_ = make_service(
        gateway=ScriptedRAGGateway(completion=make_completion()),
        strategy=strategy,
        existing_document_ids={document_id},
    )

    await service.answer(
        conversation_id=None,
        message="q",
        model_role=ModelRole.PRIMARY,
        document_id=document_id,
        filters=RetrievalFilters(filename="a.pdf"),
    )

    assert strategy.calls[0]["filters"] == RetrievalFilters(
        document_id=document_id, filename="a.pdf"
    )


async def test_filters_matching_nothing_gives_the_no_context_answer_without_calling_the_model() -> (
    None
):
    gateway = ScriptedRAGGateway(completion=make_completion())
    service, _c, messages, _s = make_service(gateway=gateway, strategy=FakeRetrievalStrategy())

    answer = await service.answer(
        conversation_id=None,
        message="q",
        model_role=ModelRole.PRIMARY,
        filters=RetrievalFilters(filename="missing.pdf"),
    )

    assert answer.has_context is False
    assert answer.answer == NO_CONTEXT_RESPONSE
    assert answer.sources == []
    assert gateway.chat_completion_calls == []
    assert answer.retrieval.filters == {"filename": "missing.pdf"}


async def test_top_k_ceiling_still_applies_with_filters() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result() for _ in range(30)])
    service, *_ = make_service(
        gateway=ScriptedRAGGateway(completion=make_completion()), strategy=strategy
    )

    await service.answer(
        conversation_id=None,
        message="q",
        model_role=ModelRole.PRIMARY,
        top_k=50,
        filters=RetrievalFilters(document_types=frozenset({DocumentType.TXT})),
    )

    assert strategy.calls[0]["top_k"] == 20  # make_settings(rag_max_results=20)


# -- SQL ---------------------------------------------------------------------------


class _Result:
    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result()


USER, ORG = uuid.uuid4(), uuid.uuid4()
SCOPE = AccessScope.for_user(user_id=USER, organization_id=ORG)


async def _compiled(filters: RetrievalFilters | None) -> tuple[str, list[Any]]:
    session = _Session()
    await RetrievalRepository(session, SCOPE).search(  # type: ignore[arg-type]
        query_vector=[0.1] * 4, model="m", model_version="1", top_k=3, filters=filters
    )
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    return str(compiled), list(compiled.params.values())


async def test_every_filter_becomes_a_bound_predicate_after_the_scope() -> None:
    document_id = uuid.uuid4()
    sql, params = await _compiled(
        RetrievalFilters(
            document_id=document_id,
            document_types=frozenset({DocumentType.PDF}),
            filename="a'; DROP TABLE documents; --",
            created_after=T0,
            created_before=T1,
        )
    )

    for fragment in (
        "documents.id =",
        "documents.document_type IN",
        "documents.original_filename =",
        "documents.created_at >=",
        "documents.created_at <=",
    ):
        assert fragment in sql
    # Values are parameters, never part of the SQL text.
    assert "DROP TABLE" not in sql
    assert "a'; DROP TABLE documents; --" in params
    assert document_id in params
    # The caller's scope is still bound, and applied before the limit.
    assert USER in params and ORG in params
    assert sql.index("documents.owner_user_id") < sql.index("LIMIT")


async def test_without_filters_only_the_scope_narrows_the_search() -> None:
    sql, _ = await _compiled(None)
    where = sql[sql.index("WHERE") : sql.index("ORDER BY")]

    assert "document_type" not in where
    assert "original_filename" not in where
    assert "created_at" not in where
    assert "documents.id" not in where


async def test_legacy_document_id_argument_still_works() -> None:
    document_id = uuid.uuid4()
    session = _Session()

    await RetrievalRepository(session, SCOPE).search(  # type: ignore[arg-type]
        query_vector=[0.1] * 4, model="m", model_version="1", top_k=3, document_id=document_id
    )

    assert (
        document_id in session.statements[0].compile(dialect=postgresql.dialect()).params.values()
    )


# -- citations in the service ------------------------------------------------------


async def test_invalid_citation_is_removed_from_answer_and_stored_message() -> None:
    gateway = ScriptedRAGGateway(
        completion=make_completion(content="Pay is monthly [S1]. Bonus is 10% [S4].")
    )
    service, _c, messages, _s = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[make_result()])
    )

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert answer.answer == "Pay is monthly [S1]. Bonus is 10%."
    assert answer.invalid_citations == ("S4",)
    assert messages.messages[-1].content == answer.answer
    assert [(s.source_id, s.cited) for s in answer.sources] == [("S1", True)]


async def test_sources_not_cited_are_marked_uncited_but_still_returned() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result(), make_result()])
    gateway = ScriptedRAGGateway(completion=make_completion(content="Only the second [S2]."))
    service, *_ = make_service(gateway=gateway, strategy=strategy)

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert [(s.source_id, s.cited) for s in answer.sources] == [("S1", False), ("S2", True)]
    assert answer.invalid_citations == ()


async def test_answer_without_citations_is_left_alone() -> None:
    gateway = ScriptedRAGGateway(completion=make_completion(content="Plain answer."))
    service, *_ = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[make_result()])
    )

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert answer.answer == "Plain answer."
    assert answer.sources[0].cited is False


async def test_no_context_answer_has_no_sources_and_nothing_to_cite() -> None:
    service, *_ = make_service(
        gateway=ScriptedRAGGateway(completion=make_completion()), strategy=FakeRetrievalStrategy()
    )

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert answer.sources == []
    assert answer.invalid_citations == ()


async def test_streamed_invalid_citation_never_reaches_the_client_or_the_store() -> None:
    chunks = [
        StreamChunk(delta="Rate is 5% ["),
        StreamChunk(delta="S"),
        StreamChunk(delta="8] and fixed [S1"),
        StreamChunk(delta="].", is_final=True, finish_reason="stop", model="m"),
    ]
    service, _c, messages, _s = make_service(
        gateway=ScriptedRAGGateway(stream_chunks=chunks),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )

    received = [
        item
        async for item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        )
    ]

    sent = "".join(chunk.delta for _id, chunk, _sources in received)
    assert "S8" not in sent
    assert sent == "Rate is 5%  and fixed [S1]."
    assert messages.messages[-1].content == sent  # what was shown is what is stored
    final_sources = received[-1][2]
    assert final_sources is not None and [s.cited for s in final_sources] == [True]


async def test_streamed_text_held_for_a_possible_marker_is_released_on_the_final_chunk() -> None:
    chunks = [StreamChunk(delta="see ["), StreamChunk(delta="S1", is_final=True)]
    service, _c, messages, _s = make_service(
        gateway=ScriptedRAGGateway(stream_chunks=chunks),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )

    received = [
        item
        async for item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        )
    ]

    assert "".join(chunk.delta for _id, chunk, _s in received) == "see [S1"
    assert messages.messages[-1].content == "see [S1"
