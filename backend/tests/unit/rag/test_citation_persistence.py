"""M10.4 T4: citation records and how `RAGService` saves them (no database: fakes only).

The similarity rule is the owner's decision of 2026-11-03 (Option A): non-finite scores are
rejected, never turned into valid ones; finite scores are clamped into [-1.0, 1.0].
"""

from __future__ import annotations

import math
from typing import Any, cast

import pytest

from app.llm.exceptions import LLMTimeoutError
from app.llm.schemas import ModelRole, StreamChunk
from app.rag.citation_records import (
    CitationIntegrityError,
    build_citation_records,
    persistable_similarity,
)
from app.rag.context.assembler import (
    PASSAGE_RENDERING_VERSION,
    ContextAssembler,
    model_visible_passage,
    passage_sha256,
)

from .doubles import FakeCitationRepository, FakeRetrievalStrategy, ScriptedRAGGateway, make_result
from .test_rag_service import make_completion, make_service

# -- the similarity rule ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_similarity_is_rejected(value: float) -> None:
    with pytest.raises(CitationIntegrityError, match="finite"):
        persistable_similarity(value)


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        (0.42, 0.42),
        (1.0, 1.0),
        (-1.0, -1.0),
        (1.0000000000000002, 1.0),  # rounding just above an exact match
        (1.5, 1.0),
        (-1.0000001, -1.0),
        (0.0, 0.0),
    ],
)
def test_a_finite_similarity_is_clamped_into_range(value: float, stored: float) -> None:
    assert persistable_similarity(value) == stored


# -- building records ------------------------------------------------------------------------------


def _assembled(*contents: str, budget: int = 10_000) -> list:
    results = [make_result(content=c, filename=f"d{i}.pdf") for i, c in enumerate(contents)]
    return ContextAssembler(max_context_chars=budget).assemble(results).sources


def test_records_mirror_the_assembled_sources_in_context_order() -> None:
    sources = _assembled("first [S3] text", "second")

    records = build_citation_records(sources, cited_ids={"S2"})

    assert [(r.source_id, r.position) for r in records] == [("S1", 1), ("S2", 2)]
    assert [r.cited for r in records] == [False, True]
    for record, source in zip(records, sources, strict=True):
        assert record.chunk_id == source.chunk_id
        assert record.document_id == source.document_id
        assert record.passage_chars == source.passage_chars
        assert record.passage_truncated == source.passage_truncated
        assert record.rendering_version == PASSAGE_RENDERING_VERSION
        assert record.passage_sha256 == source.passage_sha256


def test_a_record_lets_the_exact_passage_be_rebuilt_and_verified() -> None:
    content = "x" * 5000
    (source,) = _assembled(content, budget=100)
    (record,) = build_citation_records([source], cited_ids=())

    rebuilt = model_visible_passage(content, record.passage_chars)

    assert passage_sha256(rebuilt) == record.passage_sha256
    assert record.passage_truncated is True


def test_records_hold_no_document_text() -> None:
    (record,) = build_citation_records(_assembled("secret contract terms"), cited_ids=())

    assert "secret" not in repr(record)


def test_a_non_finite_source_score_stops_record_building() -> None:
    import dataclasses

    (source,) = _assembled("text")
    broken = dataclasses.replace(source, similarity=math.nan)

    with pytest.raises(CitationIntegrityError):
        build_citation_records([broken], cited_ids=())


def test_a_malformed_source_id_is_rejected() -> None:
    import dataclasses

    (source,) = _assembled("text")

    with pytest.raises(CitationIntegrityError, match="source id"):
        build_citation_records([dataclasses.replace(source, source_id="S01")], cited_ids=())


# -- saving through RAGService.answer ------------------------------------------------------------


def _citations(service: Any) -> FakeCitationRepository:
    return cast(FakeCitationRepository, service._citations)  # what make_service wired in


async def test_answer_saves_one_citation_per_source_under_the_reply() -> None:
    results = [make_result(content="alpha"), make_result(content="beta")]
    gateway = ScriptedRAGGateway(completion=make_completion(content="Only beta [S2]."))
    service, _c, messages, _s = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=results)
    )

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    reply = messages.messages[-1]
    assert answer.message_id == reply.id
    saved = _citations(service).saved[reply.id]
    assert [(r.source_id, r.cited) for r in saved] == [("S1", False), ("S2", True)]
    assert [r.chunk_id for r in saved] == [r.chunk_id for r in results]


async def test_a_no_context_answer_saves_no_citations_but_reports_its_message() -> None:
    service, _c, messages, _s = make_service(
        gateway=ScriptedRAGGateway(), strategy=FakeRetrievalStrategy(results=[])
    )

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert answer.message_id == messages.messages[-1].id
    assert _citations(service).saved == {}


async def test_answer_rejects_a_non_finite_score_before_calling_the_model() -> None:
    result = make_result()
    broken = type(result)(**{**result.__dict__, "similarity": math.inf})
    gateway = ScriptedRAGGateway(completion=make_completion())
    service, _c, messages, _s = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[broken])
    )

    with pytest.raises(CitationIntegrityError):
        await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert gateway.chat_completion_calls == []  # no tokens spent on a broken invariant
    assert _citations(service).saved == {}


# -- saving through RAGService.answer_stream -----------------------------------------------------


async def test_the_streamed_final_chunk_names_the_message_the_reply_is_saved_under() -> None:
    chunks = [StreamChunk(delta="Answer "), StreamChunk(delta="[S1].", is_final=True)]
    service, _c, messages, _s = make_service(
        gateway=ScriptedRAGGateway(stream_chunks=chunks),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )

    items = [
        item
        async for item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        )
    ]

    assert [item.message_id for item in items[:-1]] == [None]
    reply = messages.messages[-1]
    assert items[-1].message_id == reply.id
    assert [(r.source_id, r.cited) for r in _citations(service).saved[reply.id]] == [("S1", True)]


async def test_the_streamed_no_context_answer_names_its_saved_message() -> None:
    service, _c, messages, _s = make_service(
        gateway=ScriptedRAGGateway(), strategy=FakeRetrievalStrategy(results=[])
    )

    (item,) = [
        i
        async for i in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        )
    ]

    assert item.message_id == messages.messages[-1].id
    assert _citations(service).saved == {}


async def test_a_model_error_mid_stream_saves_no_reply_and_no_citations() -> None:
    gateway = ScriptedRAGGateway(
        stream_chunks=[StreamChunk(delta="partial")],
        stream_error=LLMTimeoutError("timed out", provider="groq"),
    )
    service, _c, messages, session = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[make_result()])
    )

    with pytest.raises(LLMTimeoutError):
        async for _ in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        ):
            pass

    assert session.rollback_calls == 1
    assert [m.role.value for m in messages.messages] == ["user"]  # rolled back by the session
    assert _citations(service).saved == {}


async def test_a_nan_score_never_reaches_the_writer_it_fails_the_retrieval_threshold() -> None:
    """`NaN >= threshold` is false, so a NaN candidate is dropped by retrieval and the answer
    is the no-context reply: nothing is cited, nothing is saved, the model is not called."""
    result = make_result()
    broken = type(result)(**{**result.__dict__, "similarity": math.nan})
    gateway = ScriptedRAGGateway(stream_chunks=[StreamChunk(delta="x", is_final=True)])
    service, *_rest = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[broken])
    )

    items = [
        i
        async for i in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        )
    ]

    assert [i.sources for i in items] == [[]]
    assert gateway.stream_calls == []
    assert _citations(service).saved == {}


async def test_the_stream_rejects_a_non_finite_score_before_any_event() -> None:
    result = make_result()
    # +infinity passes the threshold (inf >= 0.3), so it reaches record building, which rejects it.
    broken = type(result)(**{**result.__dict__, "similarity": math.inf})
    gateway = ScriptedRAGGateway(stream_chunks=[StreamChunk(delta="x", is_final=True)])
    service, *_rest = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[broken])
    )

    received = []
    with pytest.raises(CitationIntegrityError):
        async for item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        ):
            received.append(item)

    assert received == []
    assert gateway.stream_calls == []
