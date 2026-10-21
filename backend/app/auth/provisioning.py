"""Operator-side provisioning of an internal account for an external identity.

Accounts are admin-created (there is no self-service sign-up): a person can use
the API only after an operator links their identity-provider account, the
`(issuer, subject)` pair from the access token, to an internal user and
organization. This module is the safe, idempotent logic behind
`scripts/provision_identity.py`; it holds no database code of its own (a store
with the `IdentityRepository` methods is passed in) and never commits — the
caller owns the transaction.

It only ever *adds* rows. It never re-enables a disabled user or organization,
never changes an existing user's role, never moves a user between organizations
and never re-points an identity that is already linked, because doing any of
those silently would be an account takeover vector. Each of those cases is
reported as an error for the operator to resolve deliberately.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from app.domain.enums.user_role import UserRole
from app.domain.models.organization import Organization
from app.domain.models.user import User
from app.domain.models.user_identity import UserIdentity

MAX_ORGANIZATION_CHARS = 255
MAX_EMAIL_CHARS = 320
MAX_ISSUER_CHARS = 512
MAX_SUBJECT_CHARS = 255  # same bound the token verifier enforces

_UNSAFE_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class ProvisioningError(Exception):
    """The request is invalid or conflicts with existing data; nothing was changed."""


class _ProvisioningStore(Protocol):
    async def get_organization_by_name(self, name: str) -> Organization | None: ...

    async def add_organization(self, *, name: str, is_active: bool = True) -> Organization: ...

    async def get_user_by_email(self, email: str) -> User | None: ...

    async def add_user(
        self,
        *,
        organization_id: uuid.UUID,
        email: str,
        role: UserRole = UserRole.MEMBER,
        display_name: str | None = None,
        is_active: bool = True,
    ) -> User: ...

    async def get_identity(self, *, issuer: str, subject: str) -> UserIdentity | None: ...

    async def link_identity(
        self, *, user_id: uuid.UUID, issuer: str, subject: str
    ) -> UserIdentity: ...


@dataclass(frozen=True)
class ProvisioningResult:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    organization_created: bool
    user_created: bool
    identity_linked: bool

    @property
    def changed(self) -> bool:
        return self.organization_created or self.user_created or self.identity_linked


def validate_inputs(
    *, organization_name: str, email: str, issuer: str, subject: str
) -> tuple[str, str, str, str]:
    """Returns the normalized (organization, email, issuer, subject)."""
    organization = organization_name.strip()
    if not organization or len(organization) > MAX_ORGANIZATION_CHARS:
        raise ProvisioningError(
            f"The organization name must be 1-{MAX_ORGANIZATION_CHARS} characters."
        )

    email = email.strip()
    if len(email) > MAX_EMAIL_CHARS or not _EMAIL.fullmatch(email):
        raise ProvisioningError("The email address is not valid.")

    issuer = issuer.strip()
    parsed = urlparse(issuer)
    if (
        not issuer
        or len(issuer) > MAX_ISSUER_CHARS
        or _UNSAFE_CHARS.search(issuer)
        or parsed.scheme not in ("http", "https")
        or not parsed.hostname
    ):
        raise ProvisioningError(
            "The issuer must be an http(s) URL with no whitespace; it has to equal the "
            "token's `iss` claim exactly."
        )

    subject = subject.strip()
    if not subject or len(subject) > MAX_SUBJECT_CHARS or _UNSAFE_CHARS.search(subject):
        raise ProvisioningError(
            f"The subject must be 1-{MAX_SUBJECT_CHARS} characters with no whitespace; "
            "it has to equal the token's `sub` claim exactly."
        )
    return organization, email, issuer, subject


async def provision_identity(
    store: _ProvisioningStore,
    *,
    organization_name: str,
    email: str,
    issuer: str,
    subject: str,
    role: UserRole = UserRole.MEMBER,
    display_name: str | None = None,
) -> ProvisioningResult:
    """Ensures `(issuer, subject)` resolves to an active user in the organization.

    Idempotent: running it again with the same arguments changes nothing.
    """
    organization_name, email, issuer, subject = validate_inputs(
        organization_name=organization_name, email=email, issuer=issuer, subject=subject
    )

    # Read everything and check every conflict BEFORE writing anything, so a refused
    # request never leaves a partial change behind (the caller still rolls back).
    organization = await store.get_organization_by_name(organization_name)
    if organization is not None and not organization.is_active:
        raise ProvisioningError(
            f"Organization {organization_name!r} is disabled; enable it deliberately first."
        )

    user = await store.get_user_by_email(email)
    if user is not None:
        if organization is None or user.organization_id != organization.id:
            raise ProvisioningError(
                "That email already belongs to a user in a different organization."
            )
        if not user.is_active:
            raise ProvisioningError(
                "That user is disabled; re-enable the account deliberately first."
            )
        if user.role != role:
            raise ProvisioningError(
                f"That user already exists with role {user.role.value!r}, not {role.value!r}; "
                "roles are not changed by provisioning."
            )

    identity = await store.get_identity(issuer=issuer, subject=subject)
    if identity is not None and (user is None or identity.user_id != user.id):
        raise ProvisioningError(
            "That identity is already linked to a different user; it is not re-pointed."
        )

    if organization is not None and user is not None and identity is not None:
        return ProvisioningResult(
            organization_id=organization.id,
            user_id=user.id,
            organization_created=False,
            user_created=False,
            identity_linked=False,
        )

    organization_created = organization is None
    if organization is None:
        organization = await store.add_organization(name=organization_name)
    user_created = user is None
    if user is None:
        user = await store.add_user(
            organization_id=organization.id, email=email, role=role, display_name=display_name
        )
    identity_linked = identity is None
    if identity is None:
        await store.link_identity(user_id=user.id, issuer=issuer, subject=subject)
    return ProvisioningResult(
        organization_id=organization.id,
        user_id=user.id,
        organization_created=organization_created,
        user_created=user_created,
        identity_linked=identity_linked,
    )
