"""Migration 0005 upgrade -> downgrade -> upgrade, in a THROWAWAY database.

Opt-in (`RUN_MIGRATION_ROUNDTRIP=1`): it creates and drops its own uniquely
named database on the configured server and never touches the application
database (`aegis`) — so it cannot disturb other tests or real data. Skips
cleanly if the database role cannot create databases/extensions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_MIGRATION_ROUNDTRIP"),
        reason="RUN_MIGRATION_ROUNDTRIP is not set — skipping the throwaway-DB migration test",
    ),
]

_BACKEND_DIR = Path(__file__).resolve().parents[2]
IDENTITY_TABLES = {"organizations", "users", "user_identities"}


def _alembic(database_url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        # Never let a connection string (with a password) reach the test output.
        output = (result.stdout + result.stderr).replace(database_url, "<database-url>")
        pytest.fail(f"alembic {' '.join(args)} failed:\n{output[-2000:]}")


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    finally:
        await engine.dispose()


async def test_identity_migration_round_trip_in_a_throwaway_database() -> None:
    base_url = make_url(get_settings().database_url)
    name = f"aegis_migtest_{uuid.uuid4().hex[:12]}"
    admin_engine = create_async_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        try:
            async with admin_engine.connect() as conn:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
        except DBAPIError as exc:
            pytest.skip(f"cannot create a throwaway database with this role: {type(exc).__name__}")

        throwaway_url = base_url.set(database=name).render_as_string(hide_password=False)
        try:
            _alembic(throwaway_url, "upgrade", "head")
            assert await _table_names(throwaway_url) >= IDENTITY_TABLES

            _alembic(throwaway_url, "downgrade", "0004")
            tables = await _table_names(throwaway_url)
            assert not (IDENTITY_TABLES & tables)
            assert {"documents", "conversations", "chunk_embeddings"} <= tables  # untouched

            _alembic(throwaway_url, "upgrade", "head")
            assert await _table_names(throwaway_url) >= IDENTITY_TABLES
        finally:
            async with admin_engine.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await admin_engine.dispose()
