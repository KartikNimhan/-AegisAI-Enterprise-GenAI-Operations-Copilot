"""Deterministic test of run_evaluation's top-level error handling: when
the synthetic corpus can't be seeded/embedded at all (e.g. the embedding
model failed to load), the whole run must report every retrieval metric
as explicitly "skipped" with that reason — never a fabricated value, and
never an unhandled exception out of `run_evaluation` itself.

Uses a fake session (add/add_all/flush are no-ops — no real Postgres) and
monkeypatches `LocalEmbeddingProvider` in app.evaluation.runner's own
namespace to a stub whose `embed_texts` always raises, so this never
touches a real database, model, or network. The per-case retrieval path
(once seeding succeeds) is covered by the real, opt-in integration test
in backend/tests/evaluation/ instead — faking the SQLAlchemy/pgvector
query layer convincingly here would mean reimplementing it, which the
implementation brief explicitly said to avoid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.evaluation.runner as runner_module
from app.config import Settings
from app.evaluation.dataset import load_dataset
from app.evaluation.runner import run_evaluation

_DATASET = {
    "version": 1,
    "corpus": [{"id": "c1", "document_title": "Doc", "text": "Some chunk text."}],
    "cases": [{"id": "q1", "question": "A question?", "relevant_chunk_ids": ["c1"]}],
}


class _FakeSession:
    def add(self, _obj: object) -> None:
        pass

    def add_all(self, _objs: object) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _RaisingEmbeddingProvider:
    """Stands in for LocalEmbeddingProvider — always fails to embed,
    simulating e.g. no network on first model download."""

    def __init__(self, _settings: Settings) -> None:
        pass

    async def embed_texts(self, _texts: list[str]) -> list[list[float]]:
        raise RuntimeError("simulated: embedding model unavailable")

    async def embed_text(self, _text: str) -> list[float]:
        raise RuntimeError("simulated: embedding model unavailable")


async def test_run_evaluation_reports_skipped_metrics_when_seeding_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "LocalEmbeddingProvider", _RaisingEmbeddingProvider)

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(_DATASET), encoding="utf-8")
    dataset = load_dataset(dataset_path)

    report = await run_evaluation(
        session=_FakeSession(),  # type: ignore[arg-type]
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        dataset=dataset,
        top_k=3,
        dataset_path=str(dataset_path),
    )

    assert report.cases == []
    for metric_name in ("recall_at_k", "context_inclusion_rate", "operational_failure_rate"):
        entry = report.summary[metric_name]
        assert entry["status"] == "skipped"
        assert "simulated: embedding model unavailable" in entry["reason"]

    # The two LLM-dependent metrics are always skipped regardless of the
    # seeding failure — same reason as any other Phase 1 run.
    assert report.summary["answer_correctness"]["status"] == "skipped"
    assert report.summary["citation_precision"]["status"] == "skipped"


async def test_run_evaluation_never_raises_out_of_a_seeding_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the try/except around seeding: a broken
    embedding model must produce a report, not an unhandled traceback."""
    monkeypatch.setattr(runner_module, "LocalEmbeddingProvider", _RaisingEmbeddingProvider)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(_DATASET), encoding="utf-8")
    dataset = load_dataset(dataset_path)

    report = await run_evaluation(
        session=_FakeSession(),  # type: ignore[arg-type]
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        dataset=dataset,
        top_k=3,
        dataset_path=str(dataset_path),
    )

    # Reaching this line at all (no exception propagated) is the assertion.
    assert report.run_id
