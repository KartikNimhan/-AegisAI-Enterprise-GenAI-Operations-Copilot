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
and the real embedding model, over ordinary (non-no-answer) cases only:
- `recall_at_k`: fraction of each case's relevant chunks found among the
  raw top-K nearest neighbors `RetrievalRepository.search` returns (same
  measurement `backend/tests/evaluation/test_recall_at_k.py` already
  makes, now reusable against the versioned dataset file, and now a
  fraction rather than a plain hit/no-hit so a case with more than one
  relevant chunk reports partial retrieval instead of collapsing it).
- `context_inclusion_rate`: fraction of each case's relevant chunks still
  present after `RetrievalService.retrieve`'s similarity-threshold filter
  AND `ContextAssembler.assemble`'s character-budget truncation — i.e.
  would they actually have reached an LLM prompt. This can differ from
  `recall_at_k` (a chunk can be in the raw top-K but filtered out by the
  threshold, or truncated out of the context budget), so it is not a
  restatement of the same number under a different name.

A case marked `expect_no_answer=True` (see `app.evaluation.dataset`) has
no relevant chunk by design, so it is excluded from both metrics above —
see `app.evaluation.metrics`'s module docstring for why folding it in
would silently inflate them. Such a case is instead scored by
`no_answer_abstention_rate`: did `RetrievalService.retrieve` return zero
results for it (nothing cleared the real, configured similarity
threshold)?
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
    file_sha256,
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
        skipped_no_answer = metrics.skipped_metric("no_answer_abstention_rate", reason)
        return EvaluationReport(
            run_id=run_id,
            dataset_path=dataset_path,
            dataset_version=dataset.version,
            dataset_sha256=file_sha256(dataset_path),
            git_commit=git_commit,
            top_k=top_k,
            summary={
                "recall_at_k": metric_to_summary_entry(skipped),
                "context_inclusion_rate": metric_to_summary_entry(skipped_context),
                "operational_failure_rate": metric_to_summary_entry(skipped_ops),
                "no_answer_abstention_rate": metric_to_summary_entry(skipped_no_answer),
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

    recall_fractions: list[float] = []
    context_fractions: list[float] = []
    no_answer_abstentions: list[bool] = []
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

            outcome = await retrieval_service.retrieve(query=case.question, top_k=top_k)
            assembled = context_assembler.assemble(outcome.results)
            included_ids = {str(source.chunk_id) for source in assembled.sources}

            recall_fraction: float | None = None
            context_fraction: float | None = None
            no_answer_abstained: bool | None = None
            if case.expect_no_answer:
                # Nothing to compute recall over by design — see
                # app.evaluation.metrics' module docstring. Instead,
                # record whether the real, configured similarity
                # threshold excluded every candidate for this question.
                no_answer_abstained = len(outcome.results) == 0
                no_answer_abstentions.append(no_answer_abstained)
            else:
                recall_fraction = metrics.recall_fraction(retrieved_ids, relevant_db_ids)
                recall_fractions.append(recall_fraction)
                context_fraction = metrics.recall_fraction(included_ids, relevant_db_ids)
                context_fractions.append(context_fraction)

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
                    recall_fraction=recall_fraction,
                    context_inclusion_fraction=context_fraction,
                    expect_no_answer=case.expect_no_answer,
                    no_answer_abstained=no_answer_abstained,
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
                    expect_no_answer=case.expect_no_answer,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    summary = {
        "recall_at_k": metric_to_summary_entry(metrics.recall_at_k(recall_fractions)),
        "context_inclusion_rate": metric_to_summary_entry(
            metrics.context_inclusion_rate(context_fractions)
        ),
        "operational_failure_rate": metric_to_summary_entry(
            metrics.operational_failure_rate(error_count, len(dataset.cases))
        ),
        "no_answer_abstention_rate": metric_to_summary_entry(
            metrics.no_answer_abstention_rate(no_answer_abstentions)
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
        dataset_sha256=file_sha256(dataset_path),
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
