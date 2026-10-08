"""Tests for the Documents page.

No real backend/database — `services.api.documents` functions are
monkeypatched to return deterministic data shaped like
`app.api.schemas.documents`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import services.api.documents as documents_api
from services.api.client import BackendError
from services.api.documents import DocumentRecord

_PAGE_PATH = str(Path(__file__).resolve().parents[1] / "pages" / "1_Documents.py")


def _document(**overrides: object) -> DocumentRecord:
    defaults: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "filename": "Travel Policy.pdf",
        "content_type": "application/pdf",
        "document_type": "pdf",
        "file_size": 1024,
        "status": "processed",
        "error_message": None,
        "page_count": 10,
        "character_count": 5000,
        "metadata": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "processed_at": "2026-01-01T00:01:00Z",
    }
    defaults.update(overrides)
    return DocumentRecord(**defaults)


def test_successful_list_renders_each_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_api, "list_documents", lambda **kwargs: ([_document()], 1))

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    rendered = " ".join(m.value for m in at.markdown)
    assert "Travel Policy.pdf" in rendered
    assert "11111111-1111-1111-1111-111111111111" in rendered


def test_empty_list_shows_an_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_api, "list_documents", lambda **kwargs: ([], 0))

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    assert any("No documents have been uploaded yet" in i.value for i in at.info)


def test_api_failure_is_shown_as_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(**kwargs: object):
        raise BackendError("Could not reach the backend.", code="network_error")

    monkeypatch.setattr(documents_api, "list_documents", _raise)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    assert any("Unable to reach the backend" in e.value for e in at.error)


def test_document_status_is_rendered_for_each_state(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = [
        _document(id="1", filename="a.pdf", status="processed"),
        _document(id="2", filename="b.pdf", status="failed", error_message="Extraction failed"),
        _document(id="3", filename="c.pdf", status="processing"),
    ]
    monkeypatch.setattr(documents_api, "list_documents", lambda **kwargs: (docs, 3))

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    rendered = " ".join(m.value for m in at.markdown)
    assert "processed" in rendered
    assert "failed" in rendered
    assert "processing" in rendered
