"""Migrations 0006/0007 and the legacy-data assignment, end to end, in a THROWAWAY database.

Opt-in (`RUN_MIGRATION_ROUNDTRIP=1`), exactly like test_identity_migration.py: it creates
and drops its own uniquely named database on the configured server and never touches the
application database (`aegis`). Skips cleanly if the role cannot create databases/extensions.

It follows the real upgrade path for a database that already holds data from before
ownership existed (one conversation with two messages, and one document), and checks that
nothing is lost or exposed at any step:

    0005 + legacy rows
      -> 0006 (columns appear, rows untouched, owners NULL)
      -> 0007 REFUSES while rows are unowned, and the database stays at 0006
      -> scripts/assign_legacy_data.py gives the rows to a named user
      -> 0007 succeeds (owner columns NOT NULL)
      -> the database itself rejects an owner/organization mismatch
      -> downgrade to 0005 keeps every row; a fresh upgrade then refuses again
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_MIGRATION_ROUNDTRIP"),
        reason="RUN_MIGRATION_ROUNDTRIP is not set — skipping the throwaway-DB migration test",
    ),
]

_REPO = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO / "backend"
_ASSIGN_SCRIPT = _REPO / "scripts" / "assign_legacy_data.py"
OWNER_EMAIL = "owner@example.test"
OWNER_ORGANIZATION = "Acme"  # the organization seeded by _seed_legacy_data


def _run(command: list[str], database_url: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    # Never let a connection string (with a password) reach the test output.
    result.stdout = result.stdout.replace(database_url, "<database-url>")
    result.stderr = result.stderr.replace(database_url, "<database-url>")
    return result


def _alembic(database_url: str, *args: str, expect_success: bool = True) -> str:
    result = _run([sys.executable, "-m", "alembic", *args], database_url, cwd=_BACKEND_DIR)
    output = result.stdout + result.stderr
    if expect_success and result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} failed:\n{output[-2000:]}")
    if not expect_success:
        assert result.returncode != 0, f"alembic {' '.join(args)} unexpectedly succeeded"
    return output


async def _sql(database_url: str, statement: str, **params: Any) -> list[Any]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), params)
            return list(result.fetchall()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def _scalar(database_url: str, statement: str, **params: Any) -> Any:
    rows = await _sql(database_url, statement, **params)
    return rows[0][0]


async def _nullable(database_url: str, table: str, column: str) -> str:
    return await _scalar(
        database_url,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c",
        t=table,
        c=column,
    )


async def _seed_legacy_data(url: str) -> dict[str, uuid.UUID]:
    ids = {name: uuid.uuid4() for name in ("org", "user", "conversation", "document")}
    await _sql(
        url,
        "INSERT INTO organizations (id, name, is_active) VALUES (:org, 'Acme', true)",
        org=ids["org"],
    )
    await _sql(
        url,
        "INSERT INTO users (id, organization_id, email, role, is_active) "
        "VALUES (:user, :org, :email, 'member', true)",
        user=ids["user"],
        org=ids["org"],
        email=OWNER_EMAIL,
    )
    await _sql(
        url,
        "INSERT INTO conversations (id, title) VALUES (:c, 'a conversation from before ownership')",
        c=ids["conversation"],
    )
    for n, role in enumerate(("user", "assistant")):
        await _sql(
            url,
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (:m, :c, :r, :t)",
            m=uuid.uuid4(),
            c=ids["conversation"],
            r=role,
            t=f"message {n}",
        )
    await _sql(
        url,
        "INSERT INTO documents (id, filename, original_filename, content_type, document_type, "
        "file_size, checksum, status) VALUES (:d, 'key.txt', 'legacy.txt', 'text/plain', 'txt', "
        "10, :checksum, 'processed')",
        d=ids["document"],
        checksum="a" * 64,
    )
    return ids


async def _row_counts(url: str) -> tuple[int, int, int]:
    return (
        await _scalar(url, "SELECT count(*) FROM conversations"),
        await _scalar(url, "SELECT count(*) FROM messages"),
        await _scalar(url, "SELECT count(*) FROM documents"),
    )


async def test_ownership_migrations_and_backfill_in_a_throwaway_database() -> None:
    base_url = make_url(get_settings().database_url)
    name = f"aegis_ownertest_{uuid.uuid4().hex[:12]}"
    admin_engine = create_async_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        try:
            async with admin_engine.connect() as conn:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
        except DBAPIError as exc:
            pytest.skip(f"cannot create a throwaway database with this role: {type(exc).__name__}")

        url = base_url.set(database=name).render_as_string(hide_password=False)
        try:
            # -- a database as it is today: schema at 0005 plus data from before ownership ----
            _alembic(url, "upgrade", "0005")
            ids = await _seed_legacy_data(url)
            assert await _row_counts(url) == (1, 2, 1)

            # -- 0006: structure appears, no row is touched or exposed ------------------------
            _alembic(url, "upgrade", "0006")
            assert await _row_counts(url) == (1, 2, 1)
            assert await _scalar(url, "SELECT owner_user_id FROM conversations") is None
            assert await _scalar(url, "SELECT owner_user_id FROM documents") is None
            assert await _scalar(url, "SELECT visibility FROM documents") == "private"
            assert await _nullable(url, "conversations", "owner_user_id") == "YES"

            # -- 0007 refuses while rows are unowned, and leaves the database at 0006 ---------
            output = _alembic(url, "upgrade", "0007", expect_success=False)
            assert "1 conversations, 1 documents still have no owner" in output
            assert await _scalar(url, "SELECT version_num FROM alembic_version") == "0006"
            assert await _nullable(url, "conversations", "owner_user_id") == "YES"

            # -- the operator assigns the legacy rows to a named user -------------------------
            dry = _run(
                [
                    sys.executable,
                    str(_ASSIGN_SCRIPT),
                    "--email",
                    OWNER_EMAIL,
                    "--organization",
                    OWNER_ORGANIZATION,
                    "--dry-run",
                    "--expect-conversations",
                    "1",
                    "--expect-documents",
                    "1",
                ],
                url,
                cwd=_REPO,
            )
            assert dry.returncode == 0, dry.stderr
            assert await _scalar(url, "SELECT owner_user_id FROM conversations") is None

            assigned = _run(
                [
                    sys.executable,
                    str(_ASSIGN_SCRIPT),
                    "--email",
                    OWNER_EMAIL,
                    "--organization",
                    OWNER_ORGANIZATION,
                    "--yes",
                ],
                url,
                cwd=_REPO,
            )
            assert assigned.returncode == 0, assigned.stderr
            assert await _scalar(url, "SELECT owner_user_id FROM conversations") == ids["user"]
            assert await _scalar(url, "SELECT organization_id FROM conversations") == ids["org"]
            assert await _scalar(url, "SELECT owner_user_id FROM documents") == ids["user"]
            assert await _scalar(url, "SELECT visibility FROM documents") == "private"
            assert await _row_counts(url) == (1, 2, 1)  # nothing lost, messages untouched

            # a second run finds nothing to do
            again = _run(
                [
                    sys.executable,
                    str(_ASSIGN_SCRIPT),
                    "--email",
                    OWNER_EMAIL,
                    "--organization",
                    OWNER_ORGANIZATION,
                    "--yes",
                ],
                url,
                cwd=_REPO,
            )
            assert again.returncode == 0 and "nothing to assign" in again.stdout

            # -- 0007 now succeeds ----------------------------------------------------------
            _alembic(url, "upgrade", "head")
            assert await _scalar(url, "SELECT version_num FROM alembic_version") == "0007"
            assert await _nullable(url, "conversations", "owner_user_id") == "NO"
            assert await _nullable(url, "documents", "organization_id") == "NO"

            # -- the database itself rejects a row whose owner is outside its organization ----
            other_org = uuid.uuid4()
            await _sql(
                url,
                "INSERT INTO organizations (id, name, is_active) VALUES (:o, 'Other', true)",
                o=other_org,
            )
            with pytest.raises(IntegrityError):
                await _sql(
                    url,
                    "INSERT INTO conversations (id, owner_user_id, organization_id) "
                    "VALUES (:c, :u, :o)",
                    c=uuid.uuid4(),
                    u=ids["user"],
                    o=other_org,
                )
            with pytest.raises(IntegrityError):  # an owner without an organization
                await _sql(
                    url,
                    "INSERT INTO conversations (id, owner_user_id) VALUES (:c, :u)",
                    c=uuid.uuid4(),
                    u=ids["user"],
                )
            with pytest.raises(IntegrityError):  # a visibility that does not exist
                await _sql(url, "UPDATE documents SET visibility = 'public'")

            # -- a user who owns data cannot be deleted out from under it ---------------------
            with pytest.raises(IntegrityError):
                await _sql(url, "DELETE FROM users WHERE id = :u", u=ids["user"])

            # -- downgrade keeps every row; going up again refuses until owners are re-assigned
            _alembic(url, "downgrade", "0005")
            assert await _row_counts(url) == (1, 2, 1)
            _alembic(url, "upgrade", "0006")
            output = _alembic(url, "upgrade", "head", expect_success=False)
            assert "still have no owner" in output
            assert await _scalar(url, "SELECT version_num FROM alembic_version") == "0006"
        finally:
            async with admin_engine.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await admin_engine.dispose()
