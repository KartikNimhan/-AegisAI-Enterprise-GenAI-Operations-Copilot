"""Who may widen or narrow a document's visibility (AIGSEC-001).

An administrator may manage (delete, make private) any document in their organization without
reading it. Before this fix they could also *share* a member's private document with the
organization, which made it readable to themselves and everyone else: management rights turned
into read access. Now widening is for the owner only; narrowing still needs management rights.

MOCK-BASED: the session returns the document the scoped lookup would find, so this proves the
rule `DocumentRepository.set_visibility` applies once a manageable document is found. The scope
predicates themselves are proven in test_scoped_repositories.py and test_access_scope.py, and
end to end in tests/integration/test_data_isolation.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.auth.scope import AccessScope
from app.core.exceptions import DocumentShareForbiddenError
from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.models.document import Document

ORG = uuid.uuid4()
OWNER = AccessScope.for_user(user_id=uuid.uuid4(), organization_id=ORG)
ADMIN = AccessScope.for_user(user_id=uuid.uuid4(), organization_id=ORG, is_admin=True)
OPERATOR = AccessScope.unrestricted_for_operators()
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


class _Result:
    def __init__(self, document: Document | None) -> None:
        self._document = document

    def scalar_one_or_none(self) -> Document | None:
        return self._document


class SessionWith:
    def __init__(self, document: Document | None) -> None:
        self._document = document
        self.flushes = 0

    async def execute(self, statement: Any) -> _Result:
        return _Result(self._document)

    async def flush(self) -> None:
        self.flushes += 1


def _document(visibility: DocumentVisibility | None) -> Document:
    return Document(
        id=uuid.uuid4(),
        filename="key.txt",
        original_filename="policy.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        owner_user_id=OWNER.user_id,
        organization_id=ORG,
        file_size=10,
        checksum="a" * 64,
        status=DocumentStatus.PROCESSED,
        visibility=visibility,
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
    )


async def _set(scope: AccessScope, document: Document, visibility: DocumentVisibility) -> Any:
    session = SessionWith(document)
    change = await DocumentRepository(session, scope).set_visibility(  # type: ignore[arg-type]
        document.id, visibility
    )
    return change, session


async def test_the_owner_can_share_their_private_document() -> None:
    document = _document(DocumentVisibility.PRIVATE)

    change, _ = await _set(OWNER, document, DocumentVisibility.ORGANIZATION)

    assert document.visibility == DocumentVisibility.ORGANIZATION
    assert (change.previous, change.by_owner) == (DocumentVisibility.PRIVATE, True)


async def test_the_owner_can_make_their_shared_document_private_again() -> None:
    document = _document(DocumentVisibility.ORGANIZATION)

    change, _ = await _set(OWNER, document, DocumentVisibility.PRIVATE)

    assert document.visibility == DocumentVisibility.PRIVATE
    assert (change.previous, change.by_owner) == (DocumentVisibility.ORGANIZATION, True)


@pytest.mark.parametrize("stored", [DocumentVisibility.PRIVATE, None])
async def test_an_administrator_cannot_share_a_members_private_document(
    stored: DocumentVisibility | None,
) -> None:
    # `None` is a legacy row, which every reader treats as private.
    document = _document(stored)

    with pytest.raises(DocumentShareForbiddenError):
        await _set(ADMIN, document, DocumentVisibility.ORGANIZATION)

    assert document.visibility == stored  # unchanged
    assert document.updated_at == LONG_AGO


async def test_a_refused_share_flushes_nothing() -> None:
    document = _document(DocumentVisibility.PRIVATE)
    session = SessionWith(document)

    with pytest.raises(DocumentShareForbiddenError):
        await DocumentRepository(session, ADMIN).set_visibility(  # type: ignore[arg-type]
            document.id, DocumentVisibility.ORGANIZATION
        )

    assert session.flushes == 0


async def test_an_administrator_can_still_make_a_members_shared_document_private() -> None:
    document = _document(DocumentVisibility.ORGANIZATION)

    change, session = await _set(ADMIN, document, DocumentVisibility.PRIVATE)

    assert document.visibility == DocumentVisibility.PRIVATE
    assert (change.previous, change.by_owner) == (DocumentVisibility.ORGANIZATION, False)
    assert session.flushes == 1


async def test_re_saving_an_already_shared_document_as_shared_is_not_widening() -> None:
    document = _document(DocumentVisibility.ORGANIZATION)

    change, _ = await _set(ADMIN, document, DocumentVisibility.ORGANIZATION)

    assert document.visibility == DocumentVisibility.ORGANIZATION
    assert change.by_owner is False


async def test_operator_tooling_keeps_its_unrestricted_power() -> None:
    document = _document(DocumentVisibility.PRIVATE)

    change, _ = await _set(OPERATOR, document, DocumentVisibility.ORGANIZATION)

    assert document.visibility == DocumentVisibility.ORGANIZATION
    assert change.by_owner is False


async def test_a_document_the_caller_cannot_manage_is_still_just_not_found() -> None:
    session = SessionWith(None)

    change = await DocumentRepository(session, ADMIN).set_visibility(  # type: ignore[arg-type]
        uuid.uuid4(), DocumentVisibility.ORGANIZATION
    )

    assert change is None
    assert session.flushes == 0
