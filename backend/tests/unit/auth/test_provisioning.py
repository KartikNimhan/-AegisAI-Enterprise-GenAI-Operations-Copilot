"""Operator provisioning of internal accounts (`app.auth.provisioning` and
`scripts/provision_identity.py`). An in-memory store stands in for the database,
so these tests prove the rules and the command's safety behavior (nothing is
written without --yes, --dry-run rolls back, errors roll back), not the SQL; the
repository lookups have their own tests in tests/integration."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.auth.provisioning import ProvisioningError, provision_identity, validate_inputs
from app.domain.enums.user_role import UserRole
from app.domain.models.organization import Organization
from app.domain.models.user import User
from app.domain.models.user_identity import UserIdentity

ISSUER = "https://idp.example.test/realms/aegis"
SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "provision_identity.py"


class MemoryStore:
    """The slice of `IdentityRepository` that provisioning uses."""

    def __init__(self) -> None:
        self.organizations: dict[str, Organization] = {}
        self.users: dict[str, User] = {}
        self.identities: dict[tuple[str, str], UserIdentity] = {}
        self.writes = 0

    async def get_organization_by_name(self, name: str) -> Organization | None:
        return self.organizations.get(name)

    async def add_organization(self, *, name: str, is_active: bool = True) -> Organization:
        self.writes += 1
        org = Organization(id=uuid.uuid4(), name=name, is_active=is_active)
        self.organizations[name] = org
        return org

    async def get_user_by_email(self, email: str) -> User | None:
        return self.users.get(email.lower())

    async def add_user(
        self,
        *,
        organization_id: uuid.UUID,
        email: str,
        role: UserRole = UserRole.MEMBER,
        display_name: str | None = None,
        is_active: bool = True,
    ) -> User:
        self.writes += 1
        user = User(
            id=uuid.uuid4(),
            organization_id=organization_id,
            email=email,
            role=role,
            display_name=display_name,
            is_active=is_active,
        )
        self.users[email.lower()] = user
        return user

    async def get_identity(self, *, issuer: str, subject: str) -> UserIdentity | None:
        return self.identities.get((issuer, subject))

    async def link_identity(self, *, user_id: uuid.UUID, issuer: str, subject: str) -> UserIdentity:
        self.writes += 1
        identity = UserIdentity(id=uuid.uuid4(), user_id=user_id, issuer=issuer, subject=subject)
        self.identities[(issuer, subject)] = identity
        return identity


async def _provision(store: MemoryStore, **overrides: Any) -> Any:
    args: dict[str, Any] = {
        "organization_name": "Acme",
        "email": "admin@example.test",
        "issuer": ISSUER,
        "subject": "sub-1",
        "role": UserRole.ADMIN,
    }
    args.update(overrides)
    return await provision_identity(store, **args)


# -- the rules ---------------------------------------------------------------------


async def test_a_new_person_gets_an_organization_a_user_and_a_link() -> None:
    store = MemoryStore()

    result = await _provision(store, display_name="Ada")

    assert (result.organization_created, result.user_created, result.identity_linked) == (
        True,
        True,
        True,
    )
    user = store.users["admin@example.test"]
    assert (user.role, user.display_name, user.is_active) == (UserRole.ADMIN, "Ada", True)
    assert store.identities[(ISSUER, "sub-1")].user_id == user.id == result.user_id
    assert store.writes == 3


async def test_running_it_again_changes_nothing() -> None:
    store = MemoryStore()
    await _provision(store)
    writes = store.writes

    again = await _provision(store)

    assert again.changed is False
    assert store.writes == writes


async def test_an_existing_organization_and_user_are_reused_for_a_second_identity() -> None:
    store = MemoryStore()
    first = await _provision(store)

    second = await _provision(store, subject="sub-2")  # e.g. a second login method

    assert (second.organization_created, second.user_created, second.identity_linked) == (
        False,
        False,
        True,
    )
    assert second.user_id == first.user_id
    assert len(store.users) == 1 and len(store.identities) == 2


async def test_email_matching_is_case_insensitive() -> None:
    store = MemoryStore()
    await _provision(store, email="Admin@Example.TEST")

    again = await _provision(store, email="admin@example.test")

    assert again.changed is False


@pytest.mark.parametrize(
    ("setup", "overrides", "message"),
    [
        ("disabled_org", {}, "disabled"),
        ("disabled_user", {}, "disabled"),
        ("other_org", {}, "different organization"),
        ("role_differs", {"role": UserRole.MEMBER}, "role"),
        ("identity_elsewhere", {}, "already linked to a different user"),
    ],
)
async def test_conflicts_are_refused_and_nothing_is_written(
    setup: str, overrides: dict[str, Any], message: str
) -> None:
    store = MemoryStore()
    existing = await _provision(store)
    org = store.organizations["Acme"]
    user = store.users["admin@example.test"]
    if setup == "disabled_org":
        org.is_active = False
    elif setup == "disabled_user":
        user.is_active = False
    elif setup == "other_org":
        await store.add_organization(name="Other")
        overrides = {"organization_name": "Other"}
    elif setup == "identity_elsewhere":
        other = await store.add_user(
            organization_id=org.id, email="b@example.test", role=UserRole.ADMIN
        )
        store.identities[(ISSUER, "sub-9")] = UserIdentity(
            id=uuid.uuid4(), user_id=other.id, issuer=ISSUER, subject="sub-9"
        )
        overrides = {"subject": "sub-9"}
    writes = store.writes

    with pytest.raises(ProvisioningError, match=message):
        await _provision(store, **overrides)

    assert store.writes == writes  # refused before writing anything
    assert existing.user_id == user.id


async def test_an_email_in_use_cannot_be_claimed_through_a_brand_new_organization() -> None:
    store = MemoryStore()
    await _provision(store)
    writes = store.writes

    with pytest.raises(ProvisioningError, match="different organization"):
        await _provision(store, organization_name="Brand New Org", subject="sub-2")

    assert store.writes == writes
    assert "Brand New Org" not in store.organizations


@pytest.mark.parametrize(
    "overrides",
    [
        {"organization_name": "   "},
        {"organization_name": "x" * 256},
        {"email": "not-an-email"},
        {"email": "a b@example.test"},
        {"email": "a@b"},
        {"issuer": "idp.example.test/realm"},
        {"issuer": "ftp://idp.example.test"},
        {"issuer": "https://idp.example.test/realm x"},
        {"issuer": "https://idp.example.test/" + "x" * 600},
        {"subject": ""},
        {"subject": "has space"},
        {"subject": "back\\slash"},
        {"subject": "x" * 256},
    ],
)
async def test_invalid_input_is_rejected_before_any_lookup(overrides: dict[str, Any]) -> None:
    store = MemoryStore()

    with pytest.raises(ProvisioningError):
        await _provision(store, **overrides)

    assert store.writes == 0 and not store.organizations


def test_inputs_are_normalized() -> None:
    assert validate_inputs(
        organization_name=" Acme ", email=" a@b.test ", issuer=f" {ISSUER} ", subject=" s "
    ) == ("Acme", "a@b.test", ISSUER, "s")


# -- the command -------------------------------------------------------------------


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("aegisai_provision_identity_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_script()


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _Harness:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.sessions: list[_FakeSession] = []

    def session_factory(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session

    async def run(self, argv: list[str], *, issuer_default: str | None = ISSUER) -> int:
        return await cli.run(
            cli._parse_args(argv),
            issuer_default=issuer_default,
            target="db.example.test:5432/aegis",
            session_factory=self.session_factory,
            store_factory=lambda _session: self.store,
        )


BASE = ["--organization", "Acme", "--email", "admin@example.test", "--subject", "sub-1"]


async def test_without_yes_or_dry_run_nothing_is_even_attempted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness()

    code = await harness.run(BASE)

    assert code == 2
    assert harness.sessions == [] and harness.store.writes == 0
    assert "--yes" in capsys.readouterr().err


async def test_yes_commits() -> None:
    harness = _Harness()

    code = await harness.run([*BASE, "--role", "admin", "--yes"])

    assert code == 0
    (session,) = harness.sessions
    assert session.committed and not session.rolled_back
    assert harness.store.users["admin@example.test"].role == UserRole.ADMIN


async def test_dry_run_rolls_back_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    harness = _Harness()

    code = await harness.run([*BASE, "--dry-run"])

    assert code == 0
    (session,) = harness.sessions
    assert session.rolled_back and not session.committed
    assert "dry run" in capsys.readouterr().out.lower()


async def test_a_refused_request_rolls_back_and_exits_non_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness()
    await harness.run([*BASE, "--role", "admin", "--yes"])
    harness.sessions.clear()

    code = await harness.run([*BASE, "--role", "member", "--yes"])  # role mismatch

    assert code == 1
    (session,) = harness.sessions
    assert session.rolled_back and not session.committed
    assert "role" in capsys.readouterr().err


async def test_running_it_twice_reports_nothing_to_change(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness()
    await harness.run([*BASE, "--yes"])
    capsys.readouterr()

    code = await harness.run([*BASE, "--yes"])

    assert code == 0
    assert "nothing to change" in capsys.readouterr().out.lower()


async def test_the_issuer_defaults_to_the_configured_one_and_is_required_otherwise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness()
    assert await harness.run([*BASE, "--yes"]) == 0
    assert (ISSUER, "sub-1") in harness.store.identities

    other = _Harness()
    assert await other.run([*BASE, "--yes"], issuer_default=None) == 2
    assert "--issuer" in capsys.readouterr().err
    assert other.sessions == []


def test_the_printed_database_target_never_contains_the_password() -> None:
    target = cli.database_target(
        "postgresql+asyncpg://aegis:s3cret-value@db.example.test:5433/aegisdb"
    )

    assert target == "db.example.test:5433/aegisdb"
    assert "s3cret" not in target and "aegis:" not in target


def test_help_does_not_need_the_application_or_a_database(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as info:
        cli._parse_args(["--help"])

    assert info.value.code == 0
    assert "--dry-run" in capsys.readouterr().out
