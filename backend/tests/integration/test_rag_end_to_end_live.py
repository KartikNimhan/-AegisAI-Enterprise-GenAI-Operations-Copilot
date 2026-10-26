"""Opt-in end-to-end RAG test with a REAL LLM: real embeddings, real pgvector retrieval, and a real
Groq answer, checked for grounding and citations.

Every other test fakes at least one of those: test_rag_pipeline_live.py scripts the LLM and
test_groq_live.py has no retrieval. Here the question's answer exists only in a synthetic document
(a made-up room name), so a correct answer shows that the model answered from the retrieved context,
not from its own knowledge. A near-miss distractor document sits beside it.

Gates (all three are required; a missing one skips): RUN_RAG_E2E_LIVE (it calls a paid provider),
RUN_EMBEDDING_INTEGRATION (the real Sentence Transformers model) and GROQ_API_KEY. It also needs
Postgres with pgvector through the shared `db_session` fixture, which fails instead of skipping
under AEGIS_REQUIRE_SERVICES=1. All data is synthetic: nothing real is sent to the provider.
Run remotely via `.github/workflows/rag-e2e-live.yml` (manual, approval-gated).

What this does NOT prove: that a cited source semantically supports the sentence it follows
(ADR 017, D-5). Citation ids are checked against what was retrieved, and the answer must state the
one fact that only the target document contains.
"""

from __future__ import annotations

import os
import re
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.providers.local import LocalEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.llm.gateway import LLMGateway
from app.llm.schemas import ChatMessage, CompletionResponse, ModelRole, ToolSpec
from app.rag.context.assembler import ContextAssembler
from app.rag.prompts.builder import RAGPromptBuilder
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.service import RetrievalService
from app.rag.retrieval.strategy import VectorRetrievalStrategy
from app.rag.schemas import RAGAnswer
from app.rag.service import NO_CONTEXT_RESPONSE, RAGService

from .scoping import scope_of

pytestmark = [
    pytest.mark.llm_integration,
    pytest.mark.embedding_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_RAG_E2E_LIVE"),
        reason="RUN_RAG_E2E_LIVE is not set — skipping the live-LLM RAG end-to-end test "
        "(it makes real, billed provider calls)",
    ),
    pytest.mark.skipif(
        not os.environ.get("RUN_EMBEDDING_INTEGRATION"),
        reason="RUN_EMBEDDING_INTEGRATION is not set — skipping the live-LLM RAG end-to-end test "
        "(it needs the real embedding model)",
    ),
    pytest.mark.skipif(
        not os.environ.get("GROQ_API_KEY"),
        reason="GROQ_API_KEY is not set — skipping the live-LLM RAG end-to-end test",
    ),
]

# The FAST model is a reasoning model whose hidden reasoning counts against the output budget; this
# leaves room for it and a short cited answer while capping what one run can cost.
_MAX_TOKENS = 2048
_QUESTION = "In which conference room is the AegisAI disaster-recovery drill held?"
# The target (index 0) holds the only answer. The second is a deliberate near miss.
_CORPUS = [
    "The AegisAI disaster-recovery drill is held every quarter in the conference room named "
    "Larkspur-17.",
    "The AegisAI security review is held every month in the conference room named Birch-4.",
    "Dogs are loyal companions and make wonderful family pets.",
    "The stock market rallied today amid strong quarterly earnings.",
    "Quantum computers use qubits instead of classical bits.",
]
# The same marker shape app.rag.citations accepts: `[S1]`, `[S2, S3]`.
_CITATION_GROUP = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")


class _RecordingGateway(LLMGateway):
    """The REAL gateway: every call goes to the configured provider. It only records each raw
    completion (before RAGService checks its citations) and bounds the output budget."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.completions: list[CompletionResponse] = []

    async def chat_completion(
        self,
        *,
        model_role: ModelRole,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> CompletionResponse:
        completion = await super().chat_completion(
            model_role=model_role,
            messages=messages,
            temperature=temperature,
            max_tokens=_MAX_TOKENS if max_tokens is None else max_tokens,
            response_format=response_format,
            tools=tools,
        )
        self.completions.append(completion)
        return completion


async def _seed_corpus(
    db_session: AsyncSession, provider: LocalEmbeddingProvider
) -> list[DocumentChunk]:
    documents = DocumentRepository(db_session, scope_of(db_session))
    document = documents.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="aegis-operations-notes.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=1,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.PROCESSED,
    )
    await db_session.flush()
    chunks = [
        DocumentChunk(
            id=uuid.uuid4(),
            document_id=document.id,
            chunk_index=index,
            content=text,
            character_count=len(text),
        )
        for index, text in enumerate(_CORPUS)
    ]
    db_session.add_all(chunks)
    await db_session.flush()
    vectors = await provider.embed_texts([chunk.content for chunk in chunks])
    await ChunkEmbeddingRepository(db_session, scope_of(db_session)).add_all(
        [
            ChunkEmbedding(
                id=uuid.uuid4(),
                document_chunk_id=chunk.id,
                embedding=vector,
                embedding_provider=provider.name,
                embedding_model=provider.model_name,
                embedding_model_version=provider.model_version,
                embedding_dimension=provider.dimension,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
    )
    return chunks


def _rag_service(
    db_session: AsyncSession,
    settings: Settings,
    provider: LocalEmbeddingProvider,
    gateway: LLMGateway,
) -> RAGService:
    scope = scope_of(db_session)
    documents = DocumentRepository(db_session, scope)
    embedding_service = EmbeddingService(
        session=db_session,
        settings=settings,
        provider=provider,
        documents=documents,
        chunks=DocumentChunkRepository(db_session, scope),
        embeddings=ChunkEmbeddingRepository(db_session, scope),
    )
    strategy = VectorRetrievalStrategy(
        embedding_service=embedding_service, repository=RetrievalRepository(db_session, scope)
    )
    return RAGService(
        session=db_session,
        retrieval=RetrievalService(strategy=strategy, settings=settings),
        context_assembler=ContextAssembler(max_context_chars=settings.rag_max_context_chars),
        prompt_builder=RAGPromptBuilder(),
        gateway=gateway,
        conversations=ConversationRepository(db_session, scope),
        messages=MessageRepository(db_session, scope),
        documents=documents,
    )


def _cited_ids(text: str) -> set[str]:
    return {i for group in _CITATION_GROUP.findall(text) for i in re.findall(r"S\d+", group)}


def _states_the_fact(text: str) -> bool:
    # Models sometimes write a non-ASCII hyphen ("Larkspur‑17"); compare without caring.
    normalized = text.translate(_DASHES).casefold()
    return "larkspur" in normalized and "17" in normalized


def _describe(answer: RAGAnswer) -> str:
    sources = [(s.source_id, s.cited, round(s.similarity, 3)) for s in answer.sources]
    return (
        f"finish_reason={answer.finish_reason!r} invalid_citations={answer.invalid_citations!r} "
        f"sources={sources} answer={answer.answer[:400]!r}"
    )


async def test_a_real_model_answers_from_the_retrieved_evidence_and_cites_it(
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    provider = LocalEmbeddingProvider(settings)
    target = (await _seed_corpus(db_session, provider))[0]
    gateway = _RecordingGateway(settings)

    answer = await _rag_service(db_session, settings, provider, gateway).answer(
        conversation_id=None, message=_QUESTION, model_role=ModelRole.FAST
    )
    context = _describe(answer)

    # Retrieval found the evidence and handed it to the model.
    assert answer.has_context is True, context
    by_chunk = {source.chunk_id: source for source in answer.sources}
    assert target.id in by_chunk, context
    # Exactly one real provider call, with its metadata and token usage recorded.
    assert len(gateway.completions) == 1
    assert answer.provider == "groq"
    assert answer.model == settings.fast_llm_model
    assert answer.finish_reason == "stop", context
    assert answer.usage is not None and (answer.usage.total_tokens or 0) > 0, context
    # Grounding: only the synthetic target document contains this fact.
    assert _states_the_fact(answer.answer), context
    # Citation bookkeeping, guaranteed by RAGService whatever the model wrote.
    shown = _cited_ids(answer.answer)
    assert shown <= {source.source_id for source in answer.sources}, context
    assert {source.source_id for source in answer.sources if source.cited} == shown, context
    assert not set(answer.invalid_citations) & shown, context
    assert _cited_ids(gateway.completions[0].content) == shown | set(answer.invalid_citations)
    # Model behaviour, the live signal: it cited the evidence, and cited only real sources.
    assert by_chunk[target.id].cited, context
    assert answer.invalid_citations == (), context


async def test_without_qualifying_evidence_the_model_is_never_called(
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    provider = LocalEmbeddingProvider(settings)
    await _seed_corpus(db_session, provider)
    # A similarity no real query reaches: retrieval runs, but nothing qualifies as evidence.
    strict = settings.model_copy(update={"rag_similarity_threshold": 0.99})
    gateway = _RecordingGateway(strict)

    answer = await _rag_service(db_session, strict, provider, gateway).answer(
        conversation_id=None, message=_QUESTION, model_role=ModelRole.FAST
    )

    assert answer.has_context is False
    assert answer.answer == NO_CONTEXT_RESPONSE
    assert answer.sources == []
    assert answer.retrieval.candidates_found > 0  # the search ran; the threshold excluded it all
    assert answer.retrieval.similarity_threshold == 0.99
    assert gateway.completions == []  # no provider call, no cost, no fabricated certainty
