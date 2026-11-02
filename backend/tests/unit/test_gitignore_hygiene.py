"""Runtime data stays out of Git (AIGSEC-016): uploaded documents and Redis snapshots are ignored,
and the rules are narrow enough not to hide source files or test fixtures.

Static: the rules are read from .gitignore and matched with the simple glob semantics these
patterns use (no Git command is run). Ignore rules never untrack files Git already tracks.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _rules() -> list[str]:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def _ignored(path: str) -> bool:
    """Whether a path is ignored by a non-negated rule matching it or its file name."""
    ignored = False
    for rule in _rules():
        negated = rule.startswith("!")
        pattern = rule[1:] if negated else rule
        name = path.rsplit("/", 1)[-1]
        target = path if "/" in pattern.rstrip("/") else name
        if fnmatch.fnmatch(target, pattern.rstrip("/")) or path.startswith(pattern):
            ignored = not negated
    return ignored


def test_the_two_rules_exist_exactly() -> None:
    rules = _rules()

    assert "data/uploads/*" in rules
    assert "*.rdb" in rules


@pytest.mark.parametrize(
    "path",
    [
        "data/uploads/728672d0-8562-4269-bf2e-5c95304f65c4.txt",
        "data/uploads/new-upload.pdf",
        "dump.rdb",
        "backend/dump.rdb",
    ],
)
def test_runtime_uploads_and_redis_dumps_are_ignored(path: str) -> None:
    assert _ignored(path)


@pytest.mark.parametrize(
    "path",
    [
        "backend/tests/document_fixtures.py",
        "backend/app/documents/extractors/pdf.py",
        "frontend/web/src/main.tsx",
        "docs/operations/security-scanning.md",
        "infra/kubernetes/redis-deployment.yaml",
        "data/evaluation/.gitkeep",
        "data/raw/.gitkeep",
        ".env.example",
    ],
)
def test_source_fixtures_and_kept_files_are_not_ignored(path: str) -> None:
    assert not _ignored(path)


def test_the_rules_are_narrow() -> None:
    for rule in _rules():
        assert rule not in {"data/", "data/*", "*.pdf", "*.txt", "uploads/"}, rule
