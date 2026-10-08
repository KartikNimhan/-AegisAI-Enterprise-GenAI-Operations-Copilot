"""Unit tests for GET /api/v1/operations/summary.

The `DocumentRepository` dependency is overridden with a fake — no real
database is involved.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.v1.operations import get_operations_document_repository
from app.domain.enums.document_status import DocumentStatus
from app.main import app


class FakeDocumentRepository:
    def __init__(self, counts: dict[DocumentStatus, int]) -> None:
        self._counts = counts

    async def count_by_status(self) -> dict[DocumentStatus, int]:
        return self._counts


def _override(counts: dict[DocumentStatus, int]) -> None:
    app.dependency_overrides[get_operations_document_repository] = lambda: FakeDocumentRepository(
        counts
    )


def test_summary_reports_real_counts_by_status(client: TestClient) -> None:
    _override({DocumentStatus.PROCESSED: 3, DocumentStatus.FAILED: 1})

    response = client.get("/api/v1/operations/summary")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_documents"] == 4
    assert payload["documents_by_status"]["processed"] == 3
    assert payload["documents_by_status"]["failed"] == 1
    assert payload["documents_by_status"]["uploaded"] == 0
    assert payload["documents_by_status"]["processing"] == 0


def test_summary_with_no_documents_is_all_zero_not_omitted(client: TestClient) -> None:
    _override({})

    response = client.get("/api/v1/operations/summary")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_documents"] == 0
    assert set(payload["documents_by_status"].values()) == {0}
