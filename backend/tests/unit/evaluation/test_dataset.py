"""Unit tests for app.evaluation.dataset — pure JSON parsing/validation,
no database, no model, no I/O beyond reading a path the test itself
provides via tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.dataset import DatasetValidationError, load_dataset

_VALID = {
    "version": 1,
    "corpus": [
        {"id": "c1", "document_title": "Doc A", "text": "Chunk one text."},
        {"id": "c2", "document_title": "Doc A", "text": "Chunk two text."},
    ],
    "cases": [
        {"id": "q1", "question": "What is in chunk one?", "relevant_chunk_ids": ["c1"]},
    ],
}


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_a_valid_dataset(tmp_path: Path) -> None:
    dataset = load_dataset(_write(tmp_path, _VALID))

    assert dataset.version == 1
    assert len(dataset.corpus) == 2
    assert len(dataset.cases) == 1
    assert dataset.cases[0].relevant_chunk_ids == ("c1",)
    assert dataset.corpus_by_id["c1"].text == "Chunk one text."


def test_defaults_expected_answer_contains_and_category_when_absent(tmp_path: Path) -> None:
    dataset = load_dataset(_write(tmp_path, _VALID))

    assert dataset.cases[0].expected_answer_contains == ()
    assert dataset.cases[0].category == "uncategorized"


@pytest.mark.parametrize("missing_field", ["version", "corpus", "cases"])
def test_rejects_a_dataset_missing_a_top_level_field(tmp_path: Path, missing_field: str) -> None:
    payload = {k: v for k, v in _VALID.items() if k != missing_field}

    with pytest.raises(DatasetValidationError, match=missing_field):
        load_dataset(_write(tmp_path, payload))


def test_rejects_an_empty_corpus(tmp_path: Path) -> None:
    payload = {**_VALID, "corpus": []}

    with pytest.raises(DatasetValidationError, match="corpus must not be empty"):
        load_dataset(_write(tmp_path, payload))


def test_rejects_an_empty_cases_list(tmp_path: Path) -> None:
    payload = {**_VALID, "cases": []}

    with pytest.raises(DatasetValidationError, match="cases must not be empty"):
        load_dataset(_write(tmp_path, payload))


def test_rejects_a_duplicate_corpus_chunk_id(tmp_path: Path) -> None:
    payload = {
        **_VALID,
        "corpus": [
            {"id": "c1", "document_title": "Doc A", "text": "First."},
            {"id": "c1", "document_title": "Doc B", "text": "Second, duplicate id."},
        ],
    }

    with pytest.raises(DatasetValidationError, match="duplicate corpus chunk id"):
        load_dataset(_write(tmp_path, payload))


def test_rejects_a_duplicate_case_id(tmp_path: Path) -> None:
    payload = {
        **_VALID,
        "cases": [
            {"id": "q1", "question": "A?", "relevant_chunk_ids": ["c1"]},
            {"id": "q1", "question": "B?", "relevant_chunk_ids": ["c2"]},
        ],
    }

    with pytest.raises(DatasetValidationError, match="duplicate case id"):
        load_dataset(_write(tmp_path, payload))


def test_rejects_a_case_referencing_an_unknown_chunk_id(tmp_path: Path) -> None:
    """This is the exact failure mode the implementation brief warned
    about: a case's relevant_chunk_ids must only ever reference a chunk
    id that actually exists in this same dataset's corpus."""
    payload = {
        **_VALID,
        "cases": [
            {"id": "q1", "question": "What?", "relevant_chunk_ids": ["c999-does-not-exist"]},
        ],
    }

    with pytest.raises(DatasetValidationError, match="unknown corpus chunk id"):
        load_dataset(_write(tmp_path, payload))


def test_the_real_shipped_dataset_loads_and_validates() -> None:
    """Guards the actual, version-controlled dataset file against
    accidental corruption — if this fails, `scripts/evaluate.py` would
    fail identically for every real user."""
    real_path = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "evaluation"
        / "data"
        / "rag_eval_dataset.json"
    )
    dataset = load_dataset(real_path)

    assert dataset.version == 1
    assert len(dataset.corpus) >= 1
    assert len(dataset.cases) >= 1
