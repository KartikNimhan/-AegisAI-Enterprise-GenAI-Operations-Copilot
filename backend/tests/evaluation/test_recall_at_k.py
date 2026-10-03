"""Recall@K evaluation for the retrieval pipeline, against the real
Sentence Transformers model and real Postgres/pgvector.

Opt-in (same `RUN_EMBEDDING_INTEGRATION` gate as the other
`embedding_integration`-marked tests): a deterministic fake embedding would
make Recall@K meaningless, since nothing would stop the fixture from
rigging it to always "succeed" — a legitimate measurement needs the real
model.

This is a small, illustrative evaluation against a six-chunk synthetic
fixture (see rag_fixtures.py) — explicitly NOT a benchmark, and NOT a
production-scale evaluation harness. See
docs/architecture/decisions/007-rag-pipeline.md, "Evaluation approach".
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.providers.local import LocalEmbeddingProvider
from app.rag.retrieval.repository import RetrievalRepository

from .rag_fixtures import EVAL_CORPUS, EVAL_QUESTIONS

pytestmark = [
    pytest.mark.embedding_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_EMBEDDING_INTEGRATION"),
        reason="RUN_EMBEDDING_INTEGRATION is not set — skipping the real-model Recall@K evaluation",
    ),
]

_TOP_K = 3
# Illustrative floor for this tiny, topically well-separated fixture — not
# a claim about retrieval quality on any real corpus. See the ADR.
_MINIMUM_ACCEPTABLE_RECALL = 0.8


async def test_recall_at_k_against_the_synthetic_fixture(db_session: AsyncSession) -> None:
    settings = get_settings()
    provider = LocalEmbeddingProvider(settings)

    document_repo = DocumentRepository(db_session)
    document = document_repo.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="eval-corpus.txt",
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
            content=eval_chunk.text,
            character_count=len(eval_chunk.text),
        )
        for i, eval_chunk in enumerate(EVAL_CORPUS)
    ]
    db_session.add_all(chunks)
    await db_session.flush()

    vectors = await provider.embed_texts([c.text for c in EVAL_CORPUS])
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

    retrieval_repository = RetrievalRepository(db_session)
    hits = 0
    per_question_results: list[tuple[str, bool]] = []

    for eval_question in EVAL_QUESTIONS:
        query_vector = await provider.embed_text(eval_question.question)
        rows = await retrieval_repository.search(
            query_vector=query_vector,
            model=provider.model_name,
            model_version=provider.model_version,
            top_k=_TOP_K,
        )
        retrieved_texts = {chunk.content for _embedding, chunk, _document, _distance in rows}
        found = bool(retrieved_texts & set(eval_question.relevant_chunk_texts))
        per_question_results.append((eval_question.question, found))
        if found:
            hits += 1

    recall_at_k = hits / len(EVAL_QUESTIONS)
    print(f"\nRecall@{_TOP_K} = {recall_at_k:.2f} ({hits}/{len(EVAL_QUESTIONS)})")
    for question, found in per_question_results:
        print(f"  [{'HIT ' if found else 'MISS'}] {question}")

    assert recall_at_k >= _MINIMUM_ACCEPTABLE_RECALL, (
        f"Recall@{_TOP_K} was {recall_at_k:.2f} ({hits}/{len(EVAL_QUESTIONS)}); "
        f"per-question results: {per_question_results}"
    )
