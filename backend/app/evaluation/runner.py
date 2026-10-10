"""Runs the RAG evaluation dataset against the real retrieval pipeline.

Deliberately reuses the existing production classes exactly as
`RAGService` itself does — `LocalEmbeddingProvider`, `EmbeddingService`,
`VectorRetrievalStrategy`, `RetrievalService`, `ContextAssembler` — never
a second implementation of embedding/search/context-assembly logic. The
one thing this module does NOT do is call an `LLMGateway`: Phase 1 of the
evaluation framework makes no LLM call at all (no API key requirement, no
paid calls — see scripts/evaluate.py's module docstring), so any metric
that would need a real generated answer (answer correctness, citation
precision over what a model actually chose to cite) is reported via
`metrics.skipped_metric(..., SKIPPED_NO_LIVE_LLM)`, never computed
against a fabricated stand-in answer.

Two retrieval-stage metrics ARE computed for real, against real Postgres
and the real embedding model:
- `recall_at_k`: is a relevant chunk among the raw top-K nearest
  neighbors `RetrievalRepository.search` returns (same measurement
  `backend/tests/evaluation/test_recall_at_k.py` already makes, now
  reusable against the versioned dataset file instead of only the inline
  fixture).
- `context_inclusion_rate`: is a relevant chunk still present after
  `RetrievalService.retrieve`'s similarity-threshold filter AND
  `ContextAssembler.assemble`'s character-budget truncation — i.e. would
  it actually have reached an LLM prompt. This can differ from
  `recall_at_k` (a chunk can be in the raw top-K but filtered out by the
  threshold, or truncated out of the context budget), so it is not a
  restatement of the same number under a different name.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.providers.local import LocalEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.evaluation import metrics
from app.evaluation.dataset import EvalDataset
from app.evaluation.report import (
    CaseOutcome,
    EvaluationReport,
    current_git_commit,
    metric_to_summary_entry,
)
from app.rag.context.assembler import ContextAssembler
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.service import RetrievalService
from app.rag.retrieval.strategy import VectorRetrievalStrategy


class EvaluationSeedError(RuntimeError):
    """Raised when the synthetic corpus can't be embedded/seeded at all
    (e.g. the embedding model failed to load — no network on first
    download, or a corrupted cache). Distinguished from a per-case error
    because nothing downstream can be meaningfully evaluated once this
    happens — see run_evaluation's handling."""


async def run_evaluation(
    *,
    session: AsyncSession,
    settings: Settings,
    dataset: EvalDataset,
    top_k: int,
    dataset_path: str,
) -> EvaluationReport:
    run_id = datetime.now(UTC).isoformat(timespec="seconds")
    git_commit = current_git_commit()

    try:
        chunk_id_map, provider, embedding_service = await _seed_corpus(session, settings, dataset)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any seeding failure
        # means NO case can be evaluated, not just one.
        reason = f"could not seed/embed the synthetic corpus: {exc}"
        skipped = metrics.skipped_metric("recall_at_k", reason)
        skipped_context = metrics.skipped_metric("context_inclusion_rate", reason)
        skipped_ops = metrics.skipped_metric("operational_failure_rate", reason)
        return EvaluationReport(
            run_id=run_id,
            dataset_path=dataset_path,
            dataset_version=dataset.version,
            git_commit=git_commit,
            top_k=top_k,
            summary={
                "recall_at_k": metric_to_summary_entry(skipped),
                "context_inclusion_rate": metric_to_summary_entry(skipped_context),
                "operational_failure_rate": metric_to_summary_entry(skipped_ops),
                "answer_correctness": metric_to_summary_entry(
                    metrics.skipped_metric("answer_correctness", metrics.SKIPPED_NO_LIVE_LLM)
                ),
                "citation_precision": metric_to_summary_entry(
                    metrics.skipped_metric("citation_precision", metrics.SKIPPED_NO_LIVE_LLM)
                ),
            },
            cases=[],
        )

    retrieval_repository = RetrievalRepository(session)
    strategy = VectorRetrievalStrategy(
        embedding_service=embedding_service, repository=retrieval_repository
    )
    retrieval_service = RetrievalService(strategy=strategy, settings=settings)
    context_assembler = ContextAssembler(max_context_chars=settings.rag_max_context_chars)

    recall_hits: list[bool] = []
    context_hits: list[bool] = []
    case_outcomes: list[CaseOutcome] = []
    error_count = 0

    for case in dataset.cases:
        start = time.perf_counter()
        # Starts empty so the except block below always has a defined
        # value to report even if the mapping lookup itself is what
        # fails (moved inside the try so that counts as this case's
        # operational failure, not an unhandled exception out of the
        # whole run).
        relevant_db_ids: set[str] = set()
        try:
            relevant_db_ids = {chunk_id_map[cid] for cid in case.relevant_chunk_ids}
            query_vector = await provider.embed_text(case.question)
            rows = await retrieval_repository.search(
                query_vector=query_vector,
                model=provider.model_name,
                model_version=provider.model_version,
                top_k=top_k,
            )
            retrieved_ids = {str(chunk.id) for _embedding, chunk, _document, _distance in rows}
            hit = metrics.recall_hit(retrieved_ids, relevant_db_ids)
            recall_hits.append(hit)

            outcome = await retrieval_service.retrieve(query=case.question, top_k=top_k)
            assembled = context_assembler.assemble(outcome.results)
            included_ids = {str(source.chunk_id) for source in assembled.sources}
            context_hit = metrics.recall_hit(included_ids, relevant_db_ids)
            context_hits.append(context_hit)

            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            case_outcomes.append(
                CaseOutcome(
                    case_id=case.id,
                    question=case.question,
                    category=case.category,
                    status="ok",
                    duration_ms=duration_ms,
                    retrieved_chunk_ids=sorted(retrieved_ids),
                    relevant_chunk_ids=sorted(relevant_db_ids),
                    recall_hit=hit,
                    context_inclusion_hit=context_hit,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one case's operational failure
            # must never abort the whole run; it's recorded and counted.
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            error_count += 1
            case_outcomes.append(
                CaseOutcome(
                    case_id=case.id,
                    question=case.question,
                    category=case.category,
                    status="error",
                    duration_ms=duration_ms,
                    relevant_chunk_ids=sorted(relevant_db_ids),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    summary = {
        "recall_at_k": metric_to_summary_entry(metrics.recall_at_k(recall_hits)),
        "context_inclusion_rate": metric_to_summary_entry(
            metrics.context_inclusion_rate(context_hits)
        ),
        "operational_failure_rate": metric_to_summary_entry(
            metrics.operational_failure_rate(error_count, len(dataset.cases))
        ),
        "answer_correctness": metric_to_summary_entry(
            metrics.skipped_metric("answer_correctness", metrics.SKIPPED_NO_LIVE_LLM)
        ),
        "citation_precision": metric_to_summary_entry(
            metrics.skipped_metric("citation_precision", metrics.SKIPPED_NO_LIVE_LLM)
        ),
    }

    return EvaluationReport(
        run_id=run_id,
        dataset_path=dataset_path,
        dataset_version=dataset.version,
        git_commit=git_commit,
        top_k=top_k,
        summary=summary,
        cases=case_outcomes,
    )


async def _seed_corpus(
    session: AsyncSession, settings: Settings, dataset: EvalDataset
) -> tuple[dict[str, str], LocalEmbeddingProvider, EmbeddingService]:
    """Inserts the dataset's synthetic corpus as one Document + N
    DocumentChunks + their real embeddings, all within the caller's
    session — never committed (see scripts/evaluate.py: the whole run
    happens inside a transaction that is always rolled back, exactly
    like backend/tests/evaluation/conftest.py's db_session fixture).
    Returns a mapping from the dataset's own chunk ids (e.g. "c1") to the
    real database chunk ids assigned here, since those are what
    retrieval actually returns — synthetic and real ids must never be
    compared directly.
    """
    provider = LocalEmbeddingProvider(settings)
    document_repo = DocumentRepository(session)
    document = document_repo.new(
        filename=f"eval-{uuid.uuid4()}.txt",
        original_filename="evaluation-corpus.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=1,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.PROCESSED,
    )
    await session.flush()

    chunk_id_map: dict[str, str] = {}
    db_chunks: list[DocumentChunk] = []
    for i, corpus_chunk in enumerate(dataset.corpus):
        db_chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=document.id,
            chunk_index=i,
            content=corpus_chunk.text,
            character_count=len(corpus_chunk.text),
        )
        chunk_id_map[corpus_chunk.id] = str(db_chunk.id)
        db_chunks.append(db_chunk)
    session.add_all(db_chunks)
    await session.flush()

    vectors = await provider.embed_texts([c.text for c in dataset.corpus])
    embedding_repo = ChunkEmbeddingRepository(session)
    await embedding_repo.add_all(
        [
            ChunkEmbedding(
                id=uuid.uuid4(),
                document_chunk_id=db_chunk.id,
                embedding=vector,
                embedding_provider=provider.name,
                embedding_model=provider.model_name,
                embedding_model_version=provider.model_version,
                embedding_dimension=provider.dimension,
            )
            for db_chunk, vector in zip(db_chunks, vectors, strict=True)
        ]
    )

    embedding_service = EmbeddingService(
        session=session,
        settings=settings,
        provider=provider,
        documents=document_repo,
        chunks=DocumentChunkRepository(session),
        embeddings=embedding_repo,
    )
    return chunk_id_map, provider, embedding_service
