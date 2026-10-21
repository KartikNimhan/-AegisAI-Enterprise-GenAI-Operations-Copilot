"""Helpers for integration tests that need a real owner in the database.

Documents and conversations must have an owner, and every business repository applies
an access scope. The `db_session` fixture (see `conftest.py`) therefore provisions a
real organization and member user for each test and records their scope on the session;
`scope_of(db_session)` returns it. `create_user` makes further users (other members,
administrators, other organizations) for isolation tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.auth.scope import AccessScope
from app.db.repositories.identity_repository import IdentityRepository
from app.domain.enums.user_role import UserRole

TEST_ISSUER = "https://idp.example.test/realms/aegis"


@dataclass(frozen=True)
class TestUser:
    __test__ = False  # not a pytest test class

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: UserRole
    email: str

    @property
    def scope(self) -> AccessScope:
        return AccessScope.for_user(
            user_id=self.user_id,
            organization_id=self.organization_id,
            is_admin=self.role == UserRole.ADMIN,
        )

    @property
    def principal(self) -> Principal:
        return Principal(
            user_id=self.user_id,
            organization_id=self.organization_id,
            role=self.role,
            email=self.email,
            issuer=TEST_ISSUER,
        )


async def create_user(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID | None = None,
    role: UserRole = UserRole.MEMBER,
) -> TestUser:
    """Flushes (never commits) a user, in a new organization unless one is given."""
    suffix = uuid.uuid4().hex
    identities = IdentityRepository(session)
    if organization_id is None:
        organization = await identities.add_organization(name=f"test-org-{suffix}")
        organization_id = organization.id
    email = f"test-{suffix}@example.test"
    user = await identities.add_user(organization_id=organization_id, email=email, role=role)
    # Remembered so the fixture can remove every organization a test created, even after commits.
    session.info.setdefault("test_organizations", set()).add(organization_id)
    return TestUser(user_id=user.id, organization_id=organization_id, role=role, email=email)


def owner_of(session: AsyncSession) -> TestUser:
    # Not named test_*: pytest collects an imported helper with that prefix as a test.
    return session.info["test_user"]


def scope_of(session: AsyncSession) -> AccessScope:
    """The scope of the throwaway user the `db_session` fixture created for this test."""
    return owner_of(session).scope
