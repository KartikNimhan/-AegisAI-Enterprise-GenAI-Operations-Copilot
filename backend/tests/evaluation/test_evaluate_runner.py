"""Opt-in integration test for app.evaluation.runner.run_evaluation
against the real Sentence Transformers model and real Postgres/pgvector —
same `RUN_EMBEDDING_INTEGRATION` gate as test_recall_at_k.py, for the
same reason (a fake embedding would make this meaningless).

This is the strongest check that the dataset's synthetic chunk ids are
mapped correctly to the real database chunk ids retrieval actually
returns (the exact correctness concern the M11 Phase 1 brief raised) —
unlike the unit-level error-handling tests, this exercises the real
RetrievalRepository/RetrievalService/ContextAssembler query path end to
end, using the actual shipped dataset file, not an inline fixture.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.evaluation.dataset import load_dataset
from app.evaluation.runner import run_evaluation

pytestmark = [
    pytest.mark.embedding_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_EMBEDDING_INTEGRATION"),
        reason="RUN_EMBEDDING_INTEGRATION is not set — skipping the real-model "
        "evaluation runner test",
    ),
]

_DATASET_PATH = Path(__file__).parent / "data" / "rag_eval_dataset.json"


async def test_run_evaluation_against_the_real_shipped_dataset(db_session: AsyncSession) -> None:
    dataset = load_dataset(_DATASET_PATH)
    settings = get_settings()

    report = await run_evaluation(
        session=db_session,
        settings=settings,
        dataset=dataset,
        top_k=3,
        dataset_path=str(_DATASET_PATH),
    )

    assert len(report.cases) == len(dataset.cases)
    assert all(case.status == "ok" for case in report.cases), [
        (c.case_id, c.error) for c in report.cases if c.status == "error"
    ]

    # Every retrieved/relevant id recorded on each case must be a real
    # (36-character) database UUID string, never the dataset's own short
    # ids like "c1" — proves the synthetic-to-real id mapping actually
    # happened rather than silently comparing the wrong things.
    dataset_ids = {chunk.id for chunk in dataset.corpus}
    for case in report.cases:
        for chunk_id in [*case.retrieved_chunk_ids, *case.relevant_chunk_ids]:
            assert chunk_id not in dataset_ids
            assert len(chunk_id) == 36

    recall = report.summary["recall_at_k"]
    assert recall["status"] == "computed"
    print(f"\nrecall_at_k = {recall['value']:.2f}")
    assert recall["value"] >= 0.8, (
        f"recall_at_k was {recall['value']:.2f} against the real shipped dataset; "
        f"per-case: {[(c.case_id, c.recall_hit) for c in report.cases]}"
    )

    context_inclusion = report.summary["context_inclusion_rate"]
    assert context_inclusion["status"] == "computed"

    # The two LLM-dependent metrics must never be computed in this phase,
    # real infra or not.
    assert report.summary["answer_correctness"]["status"] == "skipped"
    assert report.summary["citation_precision"]["status"] == "skipped"
