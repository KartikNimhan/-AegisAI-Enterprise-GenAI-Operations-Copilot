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

from .requirements import service_unavailable

pytestmark = pytest.mark.integration

ISSUER = "https://idp.example.test/realms/aegis"


@pytest.fixture
async def repo(db_session: AsyncSession) -> IdentityRepository:
    exists = await db_session.scalar(text("select to_regclass('public.user_identities')"))
    if exists is None:
        service_unavailable(
            "migration 0005 (identity tables) has not been applied to this database"
        )
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


async def test_lookups_used_by_provisioning_find_rows_and_report_absence(
    repo: IdentityRepository,
) -> None:
    org = await repo.add_organization(name="Acme (test)")
    user = await repo.add_user(organization_id=org.id, email="Alice@Example.test")
    await repo.link_identity(user_id=user.id, issuer=ISSUER, subject="sub-1")

    assert (await repo.get_organization_by_name("Acme (test)")).id == org.id  # type: ignore[union-attr]
    assert await repo.get_organization_by_name("acme (test)") is None  # names are exact
    assert (await repo.get_user_by_email("alice@example.TEST")).id == user.id  # type: ignore[union-attr]
    assert await repo.get_user_by_email("nobody@example.test") is None
    identity = await repo.get_identity(issuer=ISSUER, subject="sub-1")
    assert identity is not None and identity.user_id == user.id
    assert await repo.get_identity(issuer=ISSUER, subject="other") is None
    assert await repo.get_identity(issuer="https://other.example.test", subject="sub-1") is None


async def test_provisioning_end_to_end_against_the_real_tables(
    repo: IdentityRepository,
) -> None:
    from app.auth.provisioning import provision_identity

    first = await provision_identity(
        repo,
        organization_name="Acme (test)",
        email="Admin@Example.test",
        issuer=ISSUER,
        subject="sub-1",
        role=UserRole.ADMIN,
    )
    again = await provision_identity(
        repo,
        organization_name="Acme (test)",
        email="admin@example.test",
        issuer=ISSUER,
        subject="sub-1",
        role=UserRole.ADMIN,
    )

    assert first.changed and not again.changed
    context = await repo.get_context(issuer=ISSUER, subject="sub-1")
    assert context is not None
    assert context.user.role == UserRole.ADMIN and context.user.id == first.user_id
