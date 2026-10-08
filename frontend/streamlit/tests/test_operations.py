"""Tests for the Operations dashboard page.

No real backend/database — `services.api.operations.get_operations_summary`
is monkeypatched. Verifies real data renders, the explicit empty state is
shown when there is nothing to report, an API failure is handled
gracefully, and no fabricated request/agent-execution metric is ever
displayed (see docs/architecture/decisions/011-copilot-ui-architecture.md,
"Dashboard data sources").
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import services.api.operations as operations_api
from services.api.client import BackendError
from services.api.operations import OperationsSummary

_PAGE_PATH = str(Path(__file__).resolve().parents[1] / "pages" / "2_Operations.py")


def test_real_data_renders_as_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = OperationsSummary(
        total_documents=4,
        documents_by_status={"uploaded": 0, "processing": 0, "processed": 3, "failed": 1},
    )
    monkeypatch.setattr(operations_api, "get_operations_summary", lambda: summary)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    metric_values = {m.label: m.value for m in at.metric}
    assert metric_values["Total documents"] == "4"
    assert metric_values["Processed"] == "3"
    assert metric_values["Failed"] == "1"


def test_no_data_shows_the_explicit_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = OperationsSummary(
        total_documents=0,
        documents_by_status={"uploaded": 0, "processing": 0, "processed": 0, "failed": 0},
    )
    monkeypatch.setattr(operations_api, "get_operations_summary", lambda: summary)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    assert any("No operational history is available yet" in i.value for i in at.info)
    assert len(at.metric) == 0


def test_api_failure_is_shown_as_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise():
        raise BackendError("An unexpected error occurred", code="internal_error")

    monkeypatch.setattr(operations_api, "get_operations_summary", _raise)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    assert any("unexpected error" in e.value.lower() for e in at.error)


def test_never_shows_a_fabricated_request_or_agent_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = OperationsSummary(total_documents=1, documents_by_status={"processed": 1})
    monkeypatch.setattr(operations_api, "get_operations_summary", lambda: summary)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    rendered = " ".join(m.label for m in at.metric)
    assert "request" not in rendered.lower()
    assert "execution" not in rendered.lower()
