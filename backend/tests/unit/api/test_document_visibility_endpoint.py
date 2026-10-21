"""PATCH /documents/{id}/visibility, and `visibility` in the document responses.

The service is a fake: it returns None exactly where the real one does when the caller is
neither the owner nor an administrator of the owner's organization, and the route must turn
that into the same 404 as a document that does not exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.models.document import Document
from app.main import app
from app.services.document_service import DocumentService, get_document_service

DOCUMENT_ID = uuid.uuid4()


def _document(visibility: DocumentVisibility | None) -> Document:
    now = datetime.now(UTC)
    return Document(
        id=DOCUMENT_ID,
        filename="key.txt",
        original_filename="policy.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=10,
        checksum="a" * 64,
        status=DocumentStatus.PROCESSED,
        visibility=visibility,
        created_at=now,
        updated_at=now,
    )


class _Service(DocumentService):
    def __init__(self, *, manageable: bool, stored: DocumentVisibility | None = None) -> None:
        self._manageable = manageable
        self._stored = stored
        self.requested: list[DocumentVisibility] = []

    async def set_visibility(
        self, document_id: uuid.UUID, visibility: DocumentVisibility
    ) -> Document | None:
        self.requested.append(visibility)
        return _document(visibility) if self._manageable else None

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        return _document(self._stored)


@pytest.fixture
def use_service() -> Iterator[Any]:
    def install(service: DocumentService) -> DocumentService:
        app.dependency_overrides[get_document_service] = lambda: service
        return service

    yield install
    app.dependency_overrides.pop(get_document_service, None)


@pytest.mark.parametrize("value", ["organization", "private"])
def test_an_owner_can_share_and_unshare(client: TestClient, use_service: Any, value: str) -> None:
    service = use_service(_Service(manageable=True))

    response = client.patch(
        f"/api/v1/documents/{DOCUMENT_ID}/visibility", json={"visibility": value}
    )

    assert response.status_code == 200
    assert response.json()["visibility"] == value
    assert service.requested == [DocumentVisibility(value)]


def test_someone_who_cannot_manage_the_document_gets_the_same_404_as_for_a_missing_one(
    client: TestClient, use_service: Any
) -> None:
    use_service(_Service(manageable=False))

    response = client.patch(
        f"/api/v1/documents/{DOCUMENT_ID}/visibility", json={"visibility": "organization"}
    )

    assert response.status_code == 404
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("http_error", "Document not found")


@pytest.mark.parametrize("body", [{"visibility": "public"}, {"visibility": ""}, {}, {"x": 1}])
def test_only_the_two_known_values_are_accepted(
    client: TestClient, use_service: Any, body: dict[str, Any]
) -> None:
    service = use_service(_Service(manageable=True))

    response = client.patch(f"/api/v1/documents/{DOCUMENT_ID}/visibility", json=body)

    assert response.status_code == 422
    assert service.requested == []  # never reached the service


def test_the_document_detail_reports_its_visibility(client: TestClient, use_service: Any) -> None:
    use_service(_Service(manageable=True, stored=DocumentVisibility.ORGANIZATION))

    response = client.get(f"/api/v1/documents/{DOCUMENT_ID}")

    assert response.status_code == 200
    assert response.json()["visibility"] == "organization"


def test_a_document_without_a_stored_visibility_is_reported_as_private(
    client: TestClient, use_service: Any
) -> None:
    use_service(_Service(manageable=True, stored=None))

    response = client.get(f"/api/v1/documents/{DOCUMENT_ID}")

    assert response.json()["visibility"] == "private"
