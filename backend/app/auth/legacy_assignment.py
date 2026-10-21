"""Gives data created before ownership existed to a named user (operator logic).

Before migration 0006/0007 conversations and documents had no owner. Migration 0006
adds the owner columns as nullable; this assigns the existing rows, and migration
0007 then requires an owner. Which user should receive them is a human decision, so
this is a command, not part of a migration.

Safe by construction, like `app.auth.provisioning`: it never guesses. The operator must name BOTH
the user (by email) and the organization (by name); both must exist, be active, and agree (the
user must belong to that organization), or nothing happens. It only ever fills in a missing
owner (rows that already belong to someone are never matched), and it never commits (the caller
owns the transaction). Optional expected counts let the operator assert exactly what will be
assigned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.domain.models.organization import Organization
from app.domain.models.user import User


class AssignmentError(Exception):
    """The request is invalid or unsafe; nothing was changed."""


class _AssignmentStore(Protocol):
    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_organization_by_name(self, name: str) -> Organization | None: ...

    async def count_unowned(self) -> tuple[int, int]: ...

    async def assign_unowned(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> tuple[int, int]: ...


@dataclass(frozen=True)
class AssignmentResult:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    conversations: int
    documents: int

    @property
    def changed(self) -> bool:
        return bool(self.conversations or self.documents)


async def assign_legacy_data(
    store: _AssignmentStore,
    *,
    email: str,
    organization_name: str,
    expect_conversations: int | None = None,
    expect_documents: int | None = None,
) -> AssignmentResult:
    """Assigns every ownerless conversation and document to the user with this email, who must
    belong to the named organization."""
    email = email.strip()
    organization_name = organization_name.strip()
    if not email or not organization_name:
        raise AssignmentError("Both the user's email and the organization's name are required.")
    user = await store.get_user_by_email(email)
    if user is None:
        raise AssignmentError(
            "No user has that email. Provision the user first (scripts/provision_identity.py)."
        )
    organization = await store.get_organization_by_name(organization_name)
    if organization is None:
        raise AssignmentError("No organization has that name.")
    if user.organization_id != organization.id:
        raise AssignmentError("That user does not belong to that organization.")
    if not user.is_active:
        raise AssignmentError("That user is disabled; data is not assigned to a disabled account.")
    if not organization.is_active:
        raise AssignmentError("That organization is disabled; data is not assigned to it.")

    conversations, documents = await store.count_unowned()
    if expect_conversations is not None and conversations != expect_conversations:
        raise AssignmentError(
            f"Expected {expect_conversations} unowned conversations but found {conversations}; "
            "nothing was changed."
        )
    if expect_documents is not None and documents != expect_documents:
        raise AssignmentError(
            f"Expected {expect_documents} unowned documents but found {documents}; "
            "nothing was changed."
        )

    if conversations or documents:
        await store.assign_unowned(user_id=user.id, organization_id=organization.id)
    return AssignmentResult(
        user_id=user.id,
        organization_id=organization.id,
        conversations=conversations,
        documents=documents,
    )
