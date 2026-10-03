"""Retrieval orchestration: resolve limits, delegate to a strategy, apply
the similarity threshold.

Deliberately has no knowledge of the LLM, prompts, or conversations —
`RAGService` is the only layer allowed to combine retrieval with
generation (see `app.rag.service`). This keeps `RetrievalService`
independently usable (and testable) for anything that only needs "find
relevant chunks for this text."
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends

from app.config import Settings
from app.dependencies import DBSessionDep, SettingsDep
from app.embeddings.service import EmbeddingService, get_embedding_service
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.schemas import RetrievalOutcome
from app.rag.retrieval.strategy import RetrievalStrategy, VectorRetrievalStrategy


class RetrievalService:
    def __init__(self, *, strategy: RetrievalStrategy, settings: Settings) -> None:
        self._strategy = strategy
        self._settings = settings

    async def retrieve(
        self,
        *,
        query: str,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        document_id: uuid.UUID | None = None,
    ) -> RetrievalOutcome:
        # The hard ceiling always applies, even to a caller-supplied top_k —
        # never let a client request an unbounded number of chunks.
        resolved_top_k = min(top_k or self._settings.rag_top_k, self._settings.rag_max_results)
        resolved_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self._settings.rag_similarity_threshold
        )

        candidates = await self._strategy.search(
            query=query, top_k=resolved_top_k, document_id=document_id
        )
        results = [c for c in candidates if c.similarity >= resolved_threshold]

        return RetrievalOutcome(
            candidates=candidates,
            results=results,
            top_k=resolved_top_k,
            similarity_threshold=resolved_threshold,
            embedding_provider=self._strategy.embedding_provider,
            embedding_model=self._strategy.embedding_model,
            embedding_model_version=self._strategy.embedding_model_version,
        )


def get_retrieval_service(
    session: DBSessionDep,
    settings: SettingsDep,
    embedding_service: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> RetrievalService:
    repository = RetrievalRepository(session)
    strategy = VectorRetrievalStrategy(embedding_service=embedding_service, repository=repository)
    return RetrievalService(strategy=strategy, settings=settings)
