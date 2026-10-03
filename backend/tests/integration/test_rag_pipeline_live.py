"""Opt-in integration test for the full RAG pipeline against the real
Sentence Transformers model and real Postgres/pgvector, with a fake
`LLMGateway` (no real Groq API key needed).

Skips automatically unless `RUN_EMBEDDING_INTEGRATION` is set — same gate
as tests/integration/test_embedding_model_live.py, since this test also
downloads/loads the real ~90MB model on first run.

Run explicitly via:
    RUN_EMBEDDING_INTEGRATION=1 uv run pytest -m embedding_integration -v
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
from app.llm.schemas import CompletionResponse, ModelRole, TokenUsage
from app.rag.context.assembler import ContextAssembler
from app.rag.prompts.builder import RAGPromptBuilder
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.service import RetrievalService
from app.rag.retrieval.strategy import VectorRetrievalStrategy
from app.rag.service import RAGService

from ..unit.rag.doubles import ScriptedRAGGateway

pytestmark = [
    pytest.mark.embedding_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_EMBEDDING_INTEGRATION"),
        reason="RUN_EMBEDDING_INTEGRATION is not set — skipping real embedding "
        "model + full RAG pipeline test (downloads/loads the real model on "
        "first run)",
    ),
]

_CORPUS = [
    ("pets", "Dogs are loyal companions and make wonderful family pets."),
    ("pets", "Cats are independent animals that enjoy quiet spaces."),
    ("finance", "The stock market rallied today amid strong quarterly earnings."),
    ("technology", "Quantum computers use qubits instead of classical bits."),
]


async def test_full_pipeline_answers_using_the_real_model_and_real_pgvector(
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    provider = LocalEmbeddingProvider(settings)

    document_repo = DocumentRepository(db_session)
    document = document_repo.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="corpus.txt",
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
            chunk_index=i,
            content=text,
            character_count=len(text),
        )
        for i, (_topic, text) in enumerate(_CORPUS)
    ]
    db_session.add_all(chunks)
    await db_session.flush()

    vectors = await provider.embed_texts([text for _topic, text in _CORPUS])
    embedding_repo = ChunkEmbeddingRepository(db_session)
    await embedding_repo.add_all(
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

    embedding_service = EmbeddingService(
        session=db_session,
        settings=settings,
        provider=provider,
        documents=document_repo,
        chunks=DocumentChunkRepository(db_session),
        embeddings=embedding_repo,
    )
    retrieval_repository = RetrievalRepository(db_session)
    strategy = VectorRetrievalStrategy(
        embedding_service=embedding_service, repository=retrieval_repository
    )
    retrieval_service = RetrievalService(strategy=strategy, settings=settings)
    gateway = ScriptedRAGGateway(
        completion=CompletionResponse(
            content="Dogs and cats are popular pets [S1][S2].",
            model="test-model",
            provider="test",
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30),
        )
    )
    rag_service = RAGService(
        session=db_session,
        retrieval=retrieval_service,
        context_assembler=ContextAssembler(max_context_chars=settings.rag_max_context_chars),
        prompt_builder=RAGPromptBuilder(),
        gateway=gateway,
        conversations=ConversationRepository(db_session),
        messages=MessageRepository(db_session),
        documents=document_repo,
    )

    answer = await rag_service.answer(
        conversation_id=None,
        message="What kinds of animals make good pets?",
        model_role=ModelRole.PRIMARY,
    )

    assert answer.has_context is True
    pets_filenames = {"corpus.txt"}
    assert all(source.filename in pets_filenames for source in answer.sources)
    retrieved_contents = {c.content for c in chunks if c.id in {s.chunk_id for s in answer.sources}}
    pets_texts = {text for topic, text in _CORPUS if topic == "pets"}
    # At least one of the two pet-related chunks should have been retrieved
    # as the nearest match — proves the real model's semantic similarity
    # ranking, not just that *some* chunk came back.
    assert retrieved_contents & pets_texts
