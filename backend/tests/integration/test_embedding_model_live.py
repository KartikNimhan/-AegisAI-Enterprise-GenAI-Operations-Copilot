"""Opt-in integration test against the real Sentence Transformers model.

Skips automatically unless `RUN_EMBEDDING_INTEGRATION` is set — a normal
`pytest` run never triggers a ~90MB model download/load, mirroring
test_groq_live.py's GROQ_API_KEY gate for the same reason. Also requires a
live Postgres (via the shared `db_session` fixture).

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
from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.providers.local import LocalEmbeddingProvider

pytestmark = [
    pytest.mark.embedding_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_EMBEDDING_INTEGRATION"),
        reason="RUN_EMBEDDING_INTEGRATION is not set — skipping real embedding "
        "model test (downloads/loads the real model on first run)",
    ),
]

_CORPUS = [
    ("pets", "The cat sat quietly on the warm windowsill all afternoon."),
    ("pets", "Dogs are loyal companions and make wonderful family pets."),
    ("finance", "The stock market rallied today amid strong quarterly earnings."),
    ("technology", "Quantum computers use qubits instead of classical bits."),
]


async def test_semantically_related_content_is_retrieved_nearest(
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
    assert all(len(vector) == provider.dimension for vector in vectors)

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

    query_vector = await provider.embed_text("Kittens and puppies make wonderful household pets.")
    results = await embedding_repo.similarity_search(
        query_vector=query_vector,
        model=provider.model_name,
        model_version=provider.model_version,
        top_k=1,
    )

    assert len(results) == 1
    _embedding, nearest_chunk, distance = results[0]
    pets_texts = {text for topic, text in _CORPUS if topic == "pets"}
    assert nearest_chunk.content in pets_texts
    assert distance < 0.5  # semantically close, not a coincidental match
