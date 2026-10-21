"""DocumentService under ownership: who can delete or re-share, and what stays separate.

The repository fakes stand in for the scoped repositories, so these tests prove the SERVICE
asks the right question (management rights, not read access, for delete and re-share) and
that identical uploads by different owners never collapse into, or collide with, each other.
The SQL behind those questions is covered in tests/unit/auth/test_access_scope.py and
tests/integration/test_data_isolation.py.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.models.document import Document

from ...document_fixtures import make_txt_bytes
from .document_doubles import FakeDocumentRepository
from .test_document_service import make_service


async def _upload(service: Any) -> Document:
    result = await service.upload(
        filename="policy.txt", content_type="text/plain", content=make_txt_bytes()
    )
    return result.document


async def test_the_same_file_uploaded_by_two_owners_is_two_documents_with_distinct_chunks() -> None:
    # Two services with separate repositories stand for two owners: duplicate detection only
    # ever looks at the caller's own documents.
    alice_service, _, alice_chunks, *_ = make_service()
    bob_service, _, bob_chunks, *_ = make_service()

    alice_result = await alice_service.upload(
        filename="policy.txt", content_type="text/plain", content=make_txt_bytes()
    )
    bob_result = await bob_service.upload(
        filename="policy.txt", content_type="text/plain", content=make_txt_bytes()
    )

    assert alice_result.is_duplicate is False and bob_result.is_duplicate is False
    assert alice_result.document.id != bob_result.document.id
    assert alice_result.document.checksum == bob_result.document.checksum  # identical bytes
    alice_ids = {chunk.id for chunk in alice_chunks.chunks}
    bob_ids = {chunk.id for chunk in bob_chunks.chunks}
    assert alice_ids and bob_ids
    assert alice_ids.isdisjoint(bob_ids)  # no primary-key collision between owners


async def test_uploading_your_own_file_twice_is_still_a_duplicate() -> None:
    service, *_ = make_service()

    first = await service.upload(
        filename="policy.txt", content_type="text/plain", content=make_txt_bytes()
    )
    second = await service.upload(
        filename="policy.txt", content_type="text/plain", content=make_txt_bytes()
    )

    assert first.is_duplicate is False and second.is_duplicate is True
    assert second.document.id == first.document.id


async def test_delete_needs_management_rights_not_read_access() -> None:
    """An administrator may remove a member's private document without being able to read it."""

    class AdministratorView(FakeDocumentRepository):
        async def get(self, document_id: uuid.UUID) -> Document | None:
            return None  # cannot read it...

        async def get_for_management(self, document_id: uuid.UUID) -> Document | None:
            return self.documents.get(document_id)  # ...but may manage it

    service, documents, _, storage, _ = make_service()
    admin_documents = AdministratorView()
    document = await _upload(service)
    admin_documents.documents = documents.documents
    service._documents = admin_documents  # type: ignore[attr-defined]

    assert await service.delete_document(document.id) is True
    assert not await storage.exists(key=document.filename)


async def test_a_reader_without_management_rights_cannot_delete() -> None:
    """A colleague can read an organization-shared document but may not delete it."""

    class ReaderView(FakeDocumentRepository):
        async def get_for_management(self, document_id: uuid.UUID) -> Document | None:
            return None

    service, documents, _, storage, _ = make_service()
    document = await _upload(service)
    reader_documents = ReaderView()
    reader_documents.documents = documents.documents
    service._documents = reader_documents  # type: ignore[attr-defined]

    assert await service.delete_document(document.id) is False
    assert await storage.exists(key=document.filename)  # the file is untouched
    assert document.id in documents.documents  # and so is the record


async def test_changing_visibility_commits_and_reports_the_updated_document() -> None:
    service, _, _, _, session = make_service()
    document = await _upload(service)
    commits_before = session.commit_count

    updated = await service.set_visibility(document.id, DocumentVisibility.ORGANIZATION)

    assert updated is not None and updated.visibility == DocumentVisibility.ORGANIZATION
    assert session.commit_count == commits_before + 1


async def test_changing_visibility_of_a_document_you_cannot_manage_changes_nothing() -> None:
    class NoManagement(FakeDocumentRepository):
        async def set_visibility(self, document_id: Any, visibility: Any) -> Document | None:
            return None

    service, documents, _, _, session = make_service()
    document = await _upload(service)
    refusing = NoManagement()
    refusing.documents = documents.documents
    service._documents = refusing  # type: ignore[attr-defined]
    commits_before = session.commit_count

    result = await service.set_visibility(document.id, DocumentVisibility.ORGANIZATION)

    assert result is None
    assert session.commit_count == commits_before  # nothing was committed
    assert document.visibility != DocumentVisibility.ORGANIZATION
