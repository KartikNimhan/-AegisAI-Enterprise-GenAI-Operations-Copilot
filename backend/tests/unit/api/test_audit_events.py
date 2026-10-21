"""Audit events for security-sensitive actions (offline: fake services, a recording logger).

Each sensitive action leaves one structured line naming WHO (user, organization, role) did WHAT
to WHICH resource id with what outcome, and nothing else: no file names, titles, message text,
e-mail addresses or tokens. An attempt on a resource the caller may not touch is recorded as
`not_found`, the same word the API returns.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import audit
from app.core.exceptions import NotFoundError
from app.domain.enums.document_visibility import DocumentVisibility
from app.embeddings.service import get_embedding_service
from app.main import app
from app.services.conversation_service import get_conversation_service
from app.services.document_service import DocumentUploadResult, get_document_service

from ...conftest import DEFAULT_TEST_PRINCIPAL
from .test_conversations_endpoint import FakeConversationService
from .test_document_visibility_endpoint import _Service as VisibilityService
from .test_documents_endpoint import FakeDocumentService, make_document
from .test_embeddings_endpoint import FakeEmbeddingService, make_result

ME = DEFAULT_TEST_PRINCIPAL


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    recorded: list[dict[str, Any]] = []

    class Recorder:
        def __getattr__(self, level: str) -> Any:
            return lambda event, **fields: recorded.append({"level": level, **fields})

    monkeypatch.setattr(audit, "logger", Recorder())
    yield recorded
    for dependency in (get_document_service, get_embedding_service, get_conversation_service):
        app.dependency_overrides.pop(dependency, None)


def only(events: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(events) == 1, events
    return events[0]


def assert_attributed_to_me(event: dict[str, Any]) -> None:
    assert event["actor_user_id"] == str(ME.user_id)
    assert event["actor_organization_id"] == str(ME.organization_id)
    assert event["actor_role"] == ME.role.value


# -- documents ---------------------------------------------------------------------------


def test_an_upload_is_recorded_with_the_new_document_id_and_whether_it_was_a_duplicate(
    client: TestClient, events: list[dict[str, Any]]
) -> None:
    document = make_document()
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService(
        upload_result=DocumentUploadResult(document=document, is_duplicate=True)
    )

    client.post("/api/v1/documents", files={"file": ("secret-plan.txt", b"x", "text/plain")})

    event = only(events)
    assert event["audit_action"] == "document.uploaded" and event["audit_outcome"] == "success"
    assert event["resource_type"] == "document" and event["resource_id"] == str(document.id)
    assert event["duplicate"] is True
    assert_attributed_to_me(event)
    assert "secret-plan" not in repr(event)  # the file name is user data and is not logged


@pytest.mark.parametrize(
    ("deletable", "outcome", "status"), [(True, "success", 204), (False, "not_found", 404)]
)
def test_a_deletion_is_recorded_whether_or_not_it_happened(
    client: TestClient, events: list[dict[str, Any]], deletable: bool, outcome: str, status: int
) -> None:
    document_id = uuid.uuid4()
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService(
        deletable=deletable
    )

    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == status
    event = only(events)
    assert event["audit_action"] == "document.deleted" and event["audit_outcome"] == outcome
    assert event["resource_id"] == str(document_id)
    assert_attributed_to_me(event)


@pytest.mark.parametrize(
    ("manageable", "outcome", "status"), [(True, "success", 200), (False, "not_found", 404)]
)
def test_sharing_changes_are_recorded_with_the_new_visibility(
    client: TestClient, events: list[dict[str, Any]], manageable: bool, outcome: str, status: int
) -> None:
    document_id = uuid.uuid4()
    app.dependency_overrides[get_document_service] = lambda: VisibilityService(
        manageable=manageable
    )

    response = client.patch(
        f"/api/v1/documents/{document_id}/visibility", json={"visibility": "organization"}
    )

    assert response.status_code == status
    event = only(events)
    assert event["audit_action"] == "document.visibility_changed"
    assert event["audit_outcome"] == outcome
    assert event["visibility"] == DocumentVisibility.ORGANIZATION.value
    assert event["resource_id"] == str(document_id)
    assert_attributed_to_me(event)


def test_an_embedding_request_is_recorded_on_success(
    client: TestClient, events: list[dict[str, Any]]
) -> None:
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService(
        embed_result=make_result()
    )
    document_id = uuid.uuid4()

    client.post(f"/api/v1/documents/{document_id}/embeddings")

    event = only(events)
    assert event["audit_action"] == "document.embedding_requested"
    assert event["audit_outcome"] == "success" and event["resource_id"] == str(document_id)


def test_an_embedding_request_for_a_document_the_caller_cannot_use_is_recorded_as_not_found(
    client: TestClient, events: list[dict[str, Any]]
) -> None:
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService(
        embed_error=NotFoundError("Document not found")
    )

    response = client.post(f"/api/v1/documents/{uuid.uuid4()}/embeddings")

    assert response.status_code == 404
    assert only(events)["audit_outcome"] == "not_found"


# -- conversations -----------------------------------------------------------------------


@pytest.mark.parametrize(("deletable", "outcome"), [(True, "success"), (False, "not_found")])
def test_deleting_a_conversation_is_recorded_without_any_of_its_content(
    client: TestClient, events: list[dict[str, Any]], deletable: bool, outcome: str
) -> None:
    conversation_id = uuid.uuid4()
    app.dependency_overrides[get_conversation_service] = lambda: FakeConversationService(
        deletable=deletable
    )

    client.delete(f"/api/v1/conversations/{conversation_id}")

    event = only(events)
    assert event["audit_action"] == "conversation.deleted" and event["audit_outcome"] == outcome
    assert event["resource_type"] == "conversation"
    assert event["resource_id"] == str(conversation_id)
    assert_attributed_to_me(event)


# -- what an event can never contain -------------------------------------------------------


def test_no_event_contains_an_email_address_or_a_token(
    client: TestClient, events: list[dict[str, Any]]
) -> None:
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService(deletable=True)

    client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    text = repr(events)
    assert ME.email not in text
    assert "test-bearer-token" not in text and "Bearer" not in text


@pytest.mark.parametrize(
    "key", ["content", "text", "message", "title", "filename", "email", "token", "authorization"]
)
def test_the_audit_helper_refuses_details_that_look_like_content_or_credentials(key: str) -> None:
    details: dict[str, Any] = {key: "anything"}
    with pytest.raises(ValueError, match="must not carry content or credentials"):
        audit.record("document.uploaded", actor=ME, resource_type="document", **details)


def test_the_audit_helper_accepts_harmless_facts(events: list[dict[str, Any]]) -> None:
    audit.record("document.uploaded", actor=ME, resource_type="document", duplicate=False, count=3)

    assert only(events)["count"] == 3
