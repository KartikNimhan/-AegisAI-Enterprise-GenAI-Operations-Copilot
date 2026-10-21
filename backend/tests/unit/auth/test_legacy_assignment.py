"""Assigning pre-ownership data to a user (`app.auth.legacy_assignment` and
`scripts/assign_legacy_data.py`). An in-memory store stands in for the database, so these
tests prove the rules and the command's safety behavior (nothing is written without --yes,
--dry-run rolls back, refusals roll back and change nothing), not the SQL."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.auth.legacy_assignment import AssignmentError, assign_legacy_data
from app.domain.enums.user_role import UserRole
from app.domain.models.organization import Organization
from app.domain.models.user import User

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "assign_legacy_data.py"
EMAIL = "owner@example.test"
ORGANIZATION = "Acme"


class MemoryStore:
    def __init__(
        self,
        *,
        conversations: int = 1,
        documents: int = 0,
        user_active: bool = True,
        org_active: bool = True,
        user_exists: bool = True,
    ) -> None:
        self.organization = Organization(id=uuid.uuid4(), name="Acme", is_active=org_active)
        self.user = (
            User(
                id=uuid.uuid4(),
                organization_id=self.organization.id,
                email=EMAIL,
                role=UserRole.MEMBER,
                is_active=user_active,
            )
            if user_exists
            else None
        )
        self.unowned = (conversations, documents)
        self.assigned: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def get_user_by_email(self, email: str) -> User | None:
        return self.user if self.user and email.lower() == EMAIL else None

    async def get_organization_by_name(self, name: str) -> Organization | None:
        return self.organization if name == ORGANIZATION else None

    async def count_unowned(self) -> tuple[int, int]:
        return self.unowned

    async def assign_unowned(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> tuple[int, int]:
        self.assigned.append((user_id, organization_id))
        result, self.unowned = self.unowned, (0, 0)  # a second run finds nothing
        return result


async def test_unowned_data_goes_to_the_user_and_their_organization() -> None:
    store = MemoryStore(conversations=1, documents=2)

    result = await assign_legacy_data(store, email=EMAIL, organization_name=ORGANIZATION)

    assert (result.conversations, result.documents) == (1, 2)
    assert store.assigned == [(store.user.id, store.organization.id)]  # type: ignore[union-attr]
    assert result.organization_id == store.organization.id  # taken from the user, never chosen


async def test_a_second_run_finds_nothing_and_writes_nothing() -> None:
    store = MemoryStore()
    await assign_legacy_data(store, email=EMAIL, organization_name=ORGANIZATION)

    again = await assign_legacy_data(store, email=EMAIL, organization_name=ORGANIZATION)

    assert again.changed is False
    assert len(store.assigned) == 1


async def test_with_nothing_unowned_nothing_is_written() -> None:
    store = MemoryStore(conversations=0, documents=0)

    result = await assign_legacy_data(store, email=EMAIL, organization_name=ORGANIZATION)

    assert result.changed is False and store.assigned == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"user_exists": False}, "No user has that email"),
        ({"user_active": False}, "disabled"),
        ({"org_active": False}, "organization is disabled"),
    ],
)
async def test_data_is_never_handed_to_a_missing_or_disabled_account(
    kwargs: dict[str, Any], message: str
) -> None:
    store = MemoryStore(**kwargs)

    with pytest.raises(AssignmentError, match=message):
        await assign_legacy_data(store, email=EMAIL, organization_name=ORGANIZATION)

    assert store.assigned == []


@pytest.mark.parametrize(
    ("expect_c", "expect_d", "message"),
    [(2, None, "Expected 2 unowned conversations but found 1"), (None, 1, "Expected 1 unowned")],
)
async def test_a_mismatch_with_the_expected_counts_changes_nothing(
    expect_c: int | None, expect_d: int | None, message: str
) -> None:
    store = MemoryStore(conversations=1, documents=0)

    with pytest.raises(AssignmentError, match=message):
        await assign_legacy_data(
            store,
            email=EMAIL,
            organization_name=ORGANIZATION,
            expect_conversations=expect_c,
            expect_documents=expect_d,
        )

    assert store.assigned == []


@pytest.mark.parametrize(
    ("email", "organization", "message"),
    [
        (EMAIL, "Some Other Org", "No organization has that name"),
        (EMAIL, "", "Both the user's email and the organization's name are required"),
        ("", ORGANIZATION, "Both the user's email and the organization's name are required"),
        ("   ", "   ", "Both the user's email and the organization's name are required"),
    ],
)
async def test_the_user_and_the_organization_must_both_be_named_and_exist(
    email: str, organization: str, message: str
) -> None:
    store = MemoryStore()

    with pytest.raises(AssignmentError, match=message):
        await assign_legacy_data(store, email=email, organization_name=organization)

    assert store.assigned == []


async def test_a_user_who_belongs_to_a_different_organization_is_refused() -> None:
    """Naming an organization the user is not in must never fall back to the user's own."""
    store = MemoryStore()
    store.user.organization_id = uuid.uuid4()  # type: ignore[union-attr]

    with pytest.raises(AssignmentError, match="does not belong to that organization"):
        await assign_legacy_data(store, email=EMAIL, organization_name=ORGANIZATION)

    assert store.assigned == []


async def test_the_organization_is_required_by_the_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli._parse_args(["--email", EMAIL, "--yes"])

    assert exit_info.value.code == 2
    assert "--organization" in capsys.readouterr().err


async def test_matching_expected_counts_proceed() -> None:
    store = MemoryStore(conversations=1, documents=0)

    result = await assign_legacy_data(
        store,
        email=EMAIL,
        organization_name=ORGANIZATION,
        expect_conversations=1,
        expect_documents=0,
    )

    assert result.changed is True


# -- the command -------------------------------------------------------------------


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("aegisai_assign_legacy_data_cli", SCRIPT)
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
    def __init__(self, **store_kwargs: Any) -> None:
        self.store = MemoryStore(**store_kwargs)
        self.sessions: list[_FakeSession] = []

    def session_factory(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session

    async def run(self, argv: list[str]) -> int:
        return await cli.run(
            cli._parse_args(argv),
            target="db.example.test:5432/aegis",
            session_factory=self.session_factory,
            store_factory=lambda _session: self.store,
        )


BASE = ["--email", EMAIL, "--organization", ORGANIZATION]


async def test_without_yes_or_dry_run_nothing_is_even_attempted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness()

    code = await harness.run(BASE)

    assert code == 2
    assert harness.sessions == [] and harness.store.assigned == []
    assert "--yes" in capsys.readouterr().err


async def test_yes_commits_and_reports_the_counts(capsys: pytest.CaptureFixture[str]) -> None:
    harness = _Harness(conversations=1, documents=0)

    code = await harness.run([*BASE, "--yes", "--expect-conversations", "1"])

    assert code == 0
    assert harness.sessions[0].committed and not harness.sessions[0].rolled_back
    assert "Assigned 1 conversation(s) and 0 document(s) to" in capsys.readouterr().out


async def test_dry_run_rolls_back_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    harness = _Harness(conversations=1)

    code = await harness.run([*BASE, "--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert harness.sessions[0].rolled_back and not harness.sessions[0].committed
    assert "[dry run, nothing written]" in out and "Would assign 1 conversation(s)" in out


async def test_a_refusal_rolls_back_and_exits_non_zero(capsys: pytest.CaptureFixture[str]) -> None:
    harness = _Harness(user_active=False)

    code = await harness.run([*BASE, "--yes"])

    assert code == 1
    assert harness.sessions[0].rolled_back and not harness.sessions[0].committed
    assert "disabled" in capsys.readouterr().err


def test_the_printed_database_target_never_contains_the_password() -> None:
    target = cli.database_target("postgresql+asyncpg://aegis:s3cr3t-pw@db.example.test:5433/aegis")

    assert target == "db.example.test:5433/aegis"
    assert "s3cr3t" not in target


def test_help_does_not_need_the_application_or_a_database(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli._parse_args(["--help"])

    assert exit_info.value.code == 0
    assert "--expect-conversations" in capsys.readouterr().out
