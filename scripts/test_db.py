"""Checks or migrates the isolated TEST database (never the development database).

    uv run python scripts/test_db.py check            # read-only status report
    uv run python scripts/test_db.py migrate --yes    # alembic upgrade head, test database only

The test database is the one named by TEST_DATABASE_URL (environment first, then `.env.test` at
the repository root). Both commands first apply the same rules as the test suite
(`backend/tests/isolation.py`): the URL must use postgresql+asyncpg, point at this machine, have no
query parameters, name a database ending in `_test`, and differ from the development database in
`.env`. Nothing connects until those rules pass.

`check` connects in a read-only session (`default_transaction_read_only=on`, so the server itself
refuses any write) and reports the server version, the `vector` extension and the Alembic revision.

`migrate --yes` connects read-only first and confirms the server reports the configured `_test`
database, then runs `alembic upgrade head` in a child process whose DATABASE_URL is the test
database. This shell's environment and the `.env` files are never changed.

This script never creates, drops or empties a database. Create the test database yourself first
(see docs/development/setup.md, "Running tests safely").

Exit codes: 0 ready / done, 1 not ready (reachable but not migrated, or `vector` missing),
2 configuration refused, 3 cannot connect or the server reports a different database,
4 the migration failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import asyncpg  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from tests.isolation import (  # noqa: E402
    DEV_ENV_FILE,
    TEST_DATABASE_URL_VAR,
    TEST_ENV_FILE,
    IsolationError,
    alembic_head,
    load_targets,
    migration_message,
    redact,
    wrong_database_message,
)

EXIT_READY = 0
EXIT_NOT_READY = 1
EXIT_REFUSED = 2
EXIT_UNREACHABLE = 3
EXIT_MIGRATION_FAILED = 4


@dataclass(frozen=True)
class DatabaseStatus:
    current_database: str
    server_version: str
    vector_installed: bool
    revision: str | None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="report the test database's status (read-only)")
    migrate = commands.add_parser("migrate", help="alembic upgrade head on the test database")
    migrate.add_argument(
        "--yes", action="store_true", help="confirm: apply the migrations to the test database"
    )
    return parser.parse_args(argv)


def _asyncpg_dsn(database_url: str) -> str:
    """The asyncpg form of a validated SQLAlchemy URL. Holds the password: never print it."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


async def read_status(database_url: str) -> DatabaseStatus:
    """Reads the status in a session the server keeps read-only."""
    connection = await asyncpg.connect(
        _asyncpg_dsn(database_url),
        timeout=5,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        current = await connection.fetchval("SELECT current_database()")
        version = await connection.fetchval("SHOW server_version")
        vector = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        has_versions = await connection.fetchval(
            "SELECT to_regclass('alembic_version') IS NOT NULL"
        )
        revision = (
            await connection.fetchval("SELECT version_num FROM alembic_version")
            if has_versions
            else None
        )
    finally:
        await connection.close()
    return DatabaseStatus(
        current_database=current,
        server_version=version,
        vector_installed=bool(vector),
        revision=revision,
    )


def _run_alembic_upgrade(database_url: str) -> int:
    """`alembic upgrade head` in a child process pointed at the test database only."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    for stream in (result.stdout, result.stderr):
        if stream:
            print(stream.replace(database_url, redact(database_url)).rstrip())
    return result.returncode


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    test_env_file: Path = TEST_ENV_FILE,
    dev_env_file: Path = DEV_ENV_FILE,
) -> int:
    args = _parse_args(argv)
    try:
        targets = load_targets(
            os.environ if environ is None else environ,
            test_env_file=test_env_file,
            dev_env_file=dev_env_file,
        )
    except IsolationError as exc:
        print(f"Refused: {exc}")
        return EXIT_REFUSED
    if not targets.database_configured:
        print(
            f"No test database is configured. Copy .env.test.example to .env.test and set "
            f"{TEST_DATABASE_URL_VAR} (see docs/development/setup.md, 'Running tests safely')."
        )
        return EXIT_REFUSED
    if args.command == "migrate" and not args.yes:
        print(
            f"Refused: this would run `alembic upgrade head` on {redact(targets.database_url)}. "
            "Add --yes to confirm."
        )
        return EXIT_REFUSED

    print(f"Test database: {redact(targets.database_url)} (from {targets.database_source})")
    try:
        status = asyncio.run(read_status(targets.database_url))
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        print(f"Cannot connect to the test database: {type(exc).__name__}")
        return EXIT_UNREACHABLE

    wrong = wrong_database_message(expected=targets.database_name, actual=status.current_database)
    if wrong is not None:
        print(wrong)
        return EXIT_UNREACHABLE

    head = alembic_head()
    print(f"Server: PostgreSQL {status.server_version}")
    print(f"vector extension: {'installed' if status.vector_installed else 'MISSING'}")
    print(f"Alembic revision: {status.revision or 'none'} (code expects {head})")

    if args.command == "migrate":
        if not status.vector_installed:
            print(
                "Refused: install the vector extension in the test database first "
                "(see docs/development/setup.md); the migrations need it."
            )
            return EXIT_NOT_READY
        print("Running alembic upgrade head on the test database ...")
        if _run_alembic_upgrade(targets.database_url) != 0:
            print("The migration failed (output above).")
            return EXIT_MIGRATION_FAILED
        status = asyncio.run(read_status(targets.database_url))
        print(f"Alembic revision now: {status.revision or 'none'}")

    problem = migration_message(
        database=status.current_database, revision=status.revision, head=head
    )
    if not status.vector_installed:
        print("Not ready: the vector extension is missing (see docs/development/setup.md).")
        return EXIT_NOT_READY
    if problem is not None:
        print(f"Not ready: {problem}")
        return EXIT_NOT_READY
    print("Ready: the test database is isolated and fully migrated.")
    return EXIT_READY


if __name__ == "__main__":
    sys.exit(main())
