"""Loads and validates the version-controlled RAG evaluation dataset.

The dataset file itself lives under
`backend/tests/evaluation/data/` (see that directory's own docstring/
`rag_eval_dataset.json` header) — a testing/evaluation fixture, not
application data, so it is not bundled into the Docker image or read by
anything at request-serving time. This module only knows how to load and
validate *a* dataset file from a given path; the default path is a
`scripts/evaluate.py`-level concern, not baked in here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class DatasetValidationError(ValueError):
    """Raised for a structurally invalid dataset — e.g. a case referencing
    a corpus chunk id that doesn't exist, or a duplicate id. Never raised
    for "the file doesn't parse as JSON" (that's a plain `ValueError` from
    `json.loads`, left to propagate with Python's own message)."""


@dataclass(frozen=True)
class EvalCorpusChunk:
    id: str
    document_title: str
    text: str


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    relevant_chunk_ids: tuple[str, ...]
    expected_answer_contains: tuple[str, ...]
    category: str


@dataclass(frozen=True)
class EvalDataset:
    version: int
    description: str
    corpus: tuple[EvalCorpusChunk, ...]
    cases: tuple[EvalCase, ...]

    @property
    def corpus_by_id(self) -> dict[str, EvalCorpusChunk]:
        return {chunk.id: chunk for chunk in self.corpus}


def load_dataset(path: Path) -> EvalDataset:
    """Reads and validates one dataset file. Raises `DatasetValidationError`
    (never returns a partially-valid dataset) for:
    - a missing required field
    - a duplicate corpus chunk id or case id
    - a case's `relevant_chunk_ids` referencing a chunk id not in `corpus`
    - an empty corpus or empty cases list
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _parse_dataset(raw, source=str(path))


def _parse_dataset(raw: dict, *, source: str) -> EvalDataset:
    for required in ("version", "corpus", "cases"):
        if required not in raw:
            raise DatasetValidationError(f"{source}: missing required field {required!r}")

    corpus_raw = raw["corpus"]
    if not corpus_raw:
        raise DatasetValidationError(f"{source}: corpus must not be empty")

    corpus: list[EvalCorpusChunk] = []
    seen_chunk_ids: set[str] = set()
    for i, entry in enumerate(corpus_raw):
        for field in ("id", "document_title", "text"):
            if field not in entry:
                raise DatasetValidationError(f"{source}: corpus[{i}] missing {field!r}")
        chunk_id = entry["id"]
        if chunk_id in seen_chunk_ids:
            raise DatasetValidationError(f"{source}: duplicate corpus chunk id {chunk_id!r}")
        seen_chunk_ids.add(chunk_id)
        corpus.append(
            EvalCorpusChunk(id=chunk_id, document_title=entry["document_title"], text=entry["text"])
        )

    cases_raw = raw["cases"]
    if not cases_raw:
        raise DatasetValidationError(f"{source}: cases must not be empty")

    cases: list[EvalCase] = []
    seen_case_ids: set[str] = set()
    for i, entry in enumerate(cases_raw):
        for field in ("id", "question", "relevant_chunk_ids"):
            if field not in entry:
                raise DatasetValidationError(f"{source}: cases[{i}] missing {field!r}")
        case_id = entry["id"]
        if case_id in seen_case_ids:
            raise DatasetValidationError(f"{source}: duplicate case id {case_id!r}")
        seen_case_ids.add(case_id)

        relevant_ids = tuple(entry["relevant_chunk_ids"])
        unknown_ids = [cid for cid in relevant_ids if cid not in seen_chunk_ids]
        if unknown_ids:
            raise DatasetValidationError(
                f"{source}: cases[{i}] ({case_id!r}) references unknown corpus "
                f"chunk id(s) {unknown_ids!r} — every relevant_chunk_ids entry "
                f"must match a corpus[].id"
            )

        cases.append(
            EvalCase(
                id=case_id,
                question=entry["question"],
                relevant_chunk_ids=relevant_ids,
                expected_answer_contains=tuple(entry.get("expected_answer_contains", [])),
                category=entry.get("category", "uncategorized"),
            )
        )

    return EvalDataset(
        version=raw["version"],
        description=raw.get("description", ""),
        corpus=tuple(corpus),
        cases=tuple(cases),
    )
