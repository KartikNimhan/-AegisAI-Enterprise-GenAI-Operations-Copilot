"""Identity mapping: a verified (issuer, subject) -> a principal built ONLY
from the database row (role, organization, email, active flags)."""

from __future__ import annotations

import pytest

from app.auth.exceptions import AccountDisabledError, IdentityNotLinkedError
from app.auth.service import IdentityService
from app.auth.tokens import VerifiedClaims
from app.domain.enums.user_role import UserRole

from ...auth_fixtures import ISSUER, FakeIdentityRepository


def _claims(**overrides: object) -> VerifiedClaims:
    values: dict[str, object] = {
        "issuer": ISSUER,
        "subject": "subject-1",
        "email": "claim-email@example.test",
        "email_verified": True,
        "token_id": "jti-9",
        "expires_at": 4102444800,
    }
    values.update(overrides)
    return VerifiedClaims(**values)  # type: ignore[arg-type]


async def test_resolves_a_linked_active_user_from_the_database_row() -> None:
    repo = FakeIdentityRepository()
    context = repo.link(email="db-user@example.test", role=UserRole.ADMIN)

    principal = await IdentityService(repo).resolve_principal(_claims())

    assert principal.user_id == context.user.id
    assert principal.organization_id == context.organization.id
    assert principal.role == UserRole.ADMIN
    # Email comes from the database, not from the token's claim.
    assert principal.email == "db-user@example.test"
    assert principal.token_id == "jti-9"
    assert principal.is_admin is True


async def test_an_unknown_identity_is_rejected_and_never_created() -> None:
    repo = FakeIdentityRepository()

    with pytest.raises(IdentityNotLinkedError):
        await IdentityService(repo).resolve_principal(_claims(subject="stranger"))

    assert repo.lookups == 1


async def test_the_same_subject_from_a_different_issuer_is_a_different_identity() -> None:
    repo = FakeIdentityRepository()
    repo.link(subject="subject-1", issuer=ISSUER)

    with pytest.raises(IdentityNotLinkedError):
        await IdentityService(repo).resolve_principal(
            _claims(issuer="https://other-idp.example.test/realms/x")
        )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"user_active": False}, "user_disabled"),
        ({"organization_active": False}, "organization_disabled"),
    ],
)
async def test_disabled_users_and_organizations_are_rejected(kwargs: dict, reason: str) -> None:
    repo = FakeIdentityRepository()
    repo.link(**kwargs)

    with pytest.raises(AccountDisabledError) as info:
        await IdentityService(repo).resolve_principal(_claims())

    assert info.value.reason == reason
