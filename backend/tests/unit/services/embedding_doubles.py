"""Test doubles for EmbeddingService unit tests.

Not a test module itself (no `test_*` functions). None of these touch a
real database or a real embedding model.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.base import EmbeddingProvider


class FakeEmbeddingProvider(EmbeddingProvider):
    """Scripted by `effects` (like `ScriptedProvider` in `tests/unit/llm`):
    each `embed_texts` call pops one effect — an `Exception` to raise, or a
    `list[list[float]]` to return. With `effects=None`, returns a
    deterministic fake vector per input text instead.
    """

    def __init__(
        self,
        *,
        name: str = "fake",
        model_name: str = "fake-model",
        model_version: str = "1",
        dimension: int = 8,
        effects: list[Any] | None = None,
    ) -> None:
        self._name = name
        self._model_name = model_name
        self._model_version = model_version
        self._dimension = dimension
        self._effects = effects
        self.calls: list[list[str]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self._effects is not None:
            effect = self._effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return [[float(len(text) % 7)] * self._dimension for text in texts]


class _FakeNestedTransaction:
    async def __aenter__(self) -> _FakeNestedTransaction:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class FakeSession:
    """Stand-in for AsyncSession — only what EmbeddingService calls directly."""

    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction()


class FakeDocumentChunkRepository:
    def __init__(self, chunks: list[DocumentChunk] | None = None) -> None:
        self.chunks: list[DocumentChunk] = chunks or []

    async def add_all(self, chunks: list[DocumentChunk]) -> None:
        self.chunks.extend(chunks)

    async def list_by_document(
        self, document_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[DocumentChunk], int]:
        matching = [c for c in self.chunks if c.document_id == document_id]
        return matching[offset : offset + limit], len(matching)

    async def count_by_document(self, document_id: uuid.UUID) -> int:
        return sum(1 for c in self.chunks if c.document_id == document_id)


class FakeChunkEmbeddingRepository:
    def __init__(
        self,
        *,
        chunks: FakeDocumentChunkRepository,
        fail_add: bool = False,
        scripted_matches: list[tuple[ChunkEmbedding, DocumentChunk, float]] | None = None,
    ) -> None:
        self.embeddings: list[ChunkEmbedding] = []
        self._chunks = chunks
        self._fail_add = fail_add
        self._scripted_matches = scripted_matches or []
        self.similarity_search_calls: list[dict[str, Any]] = []

    async def add_all(self, embeddings: list[ChunkEmbedding]) -> None:
        if self._fail_add:
            raise RuntimeError("Simulated embedding persistence failure")
        existing_keys = {
            (e.document_chunk_id, e.embedding_model, e.embedding_model_version)
            for e in self.embeddings
        }
        for embedding in embeddings:
            key = (
                embedding.document_chunk_id,
                embedding.embedding_model,
                embedding.embedding_model_version,
            )
            if key in existing_keys:
                raise RuntimeError("Simulated unique constraint violation")
            existing_keys.add(key)
        self.embeddings.extend(embeddings)

    async def get_embedded_chunk_ids(
        self, chunk_ids: list[uuid.UUID], *, model: str, model_version: str
    ) -> set[uuid.UUID]:
        return {
            e.document_chunk_id
            for e in self.embeddings
            if e.document_chunk_id in chunk_ids
            and e.embedding_model == model
            and e.embedding_model_version == model_version
        }

    async def count_for_document(
        self, document_id: uuid.UUID, *, model: str, model_version: str
    ) -> int:
        chunk_ids = {c.id for c in self._chunks.chunks if c.document_id == document_id}
        return sum(
            1
            for e in self.embeddings
            if e.document_chunk_id in chunk_ids
            and e.embedding_model == model
            and e.embedding_model_version == model_version
        )

    async def similarity_search(
        self,
        *,
        query_vector: list[float],
        model: str,
        model_version: str,
        top_k: int = 5,
    ) -> list[tuple[ChunkEmbedding, DocumentChunk, float]]:
        self.similarity_search_calls.append(
            {
                "query_vector": query_vector,
                "model": model,
                "model_version": model_version,
                "top_k": top_k,
            }
        )
        return self._scripted_matches[:top_k]
