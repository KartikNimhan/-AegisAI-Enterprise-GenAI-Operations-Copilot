"""Identity tables against a real Postgres (transactional: nothing is ever
committed). Requires migration 0005; skips with an explicit reason if the
tables do not exist yet (CI applies migrations before running tests)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.identity_repository import IdentityRepository
from app.domain.enums.user_role import UserRole

pytestmark = pytest.mark.integration

ISSUER = "https://idp.example.test/realms/aegis"


@pytest.fixture
async def repo(db_session: AsyncSession) -> IdentityRepository:
    exists = await db_session.scalar(text("select to_regclass('public.user_identities')"))
    if exists is None:
        pytest.skip("migration 0005 (identity tables) has not been applied to this database")
    return IdentityRepository(db_session)


async def test_a_linked_identity_resolves_to_its_user_and_organization(
    repo: IdentityRepository,
) -> None:
    org = await repo.add_organization(name="Acme (test)")
    user = await repo.add_user(
        organization_id=org.id, email="Alice@Example.test", role=UserRole.ADMIN
    )
    await repo.link_identity(user_id=user.id, issuer=ISSUER, subject="sub-1")

    context = await repo.get_context(issuer=ISSUER, subject="sub-1")

    assert context is not None
    assert context.user.id == user.id
    assert context.user.role == UserRole.ADMIN
    assert context.organization.id == org.id
    assert context.user.is_active and context.organization.is_active


async def test_unknown_subject_or_issuer_resolves_to_nothing(repo: IdentityRepository) -> None:
    org = await repo.add_organization(name="Acme (test)")
    user = await repo.add_user(organization_id=org.id, email="a@example.test")
    await repo.link_identity(user_id=user.id, issuer=ISSUER, subject="sub-1")

    assert await repo.get_context(issuer=ISSUER, subject="other") is None
    assert await repo.get_context(issuer="https://other.example.test", subject="sub-1") is None


async def test_email_uniqueness_is_case_insensitive(
    repo: IdentityRepository, db_session: AsyncSession
) -> None:
    org = await repo.add_organization(name="Acme (test)")
    await repo.add_user(organization_id=org.id, email="Alice@Example.test")

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repo.add_user(organization_id=org.id, email="alice@example.TEST")


async def test_an_external_identity_can_link_to_only_one_user(
    repo: IdentityRepository, db_session: AsyncSession
) -> None:
    org = await repo.add_organization(name="Acme (test)")
    first = await repo.add_user(organization_id=org.id, email="a@example.test")
    second = await repo.add_user(organization_id=org.id, email="b@example.test")
    await repo.link_identity(user_id=first.id, issuer=ISSUER, subject="sub-1")

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repo.link_identity(user_id=second.id, issuer=ISSUER, subject="sub-1")


async def test_organization_names_are_unique(
    repo: IdentityRepository, db_session: AsyncSession
) -> None:
    await repo.add_organization(name="Acme (test)")

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repo.add_organization(name="Acme (test)")


async def test_deleting_a_user_removes_its_identity_links(
    repo: IdentityRepository, db_session: AsyncSession
) -> None:
    org = await repo.add_organization(name="Acme (test)")
    user = await repo.add_user(organization_id=org.id, email="a@example.test")
    await repo.link_identity(user_id=user.id, issuer=ISSUER, subject="sub-1")

    await db_session.execute(text("delete from users where id = :id"), {"id": user.id})
    db_session.expire_all()

    assert await repo.get_context(issuer=ISSUER, subject="sub-1") is None


async def test_disabled_flags_round_trip(repo: IdentityRepository) -> None:
    org = await repo.add_organization(name="Acme (test)", is_active=False)
    user = await repo.add_user(organization_id=org.id, email="a@example.test", is_active=False)
    await repo.link_identity(user_id=user.id, issuer=ISSUER, subject="sub-1")

    context = await repo.get_context(issuer=ISSUER, subject="sub-1")

    assert context is not None
    assert context.user.is_active is False
    assert context.organization.is_active is False
