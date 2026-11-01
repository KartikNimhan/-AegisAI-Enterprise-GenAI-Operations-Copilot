"""A failed query must not write its bound values into the logs (AIGSEC-004).

When a statement fails, SQLAlchemy's error text normally ends with `[parameters: (...)]`, and the
unhandled-exception handler logs that text with the traceback (`logger.exception`). The values can
be user ids, e-mail addresses, search queries or document text. `engine_options` turns on
`hide_parameters` for every application engine.

The behaviour is proven on a throwaway in-memory SQLite engine built with the SAME options the
application uses: `hide_parameters` is handled by SQLAlchemy's core, not by the database driver,
so the result carries over to asyncpg. No real database is touched.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, StatementError

from app.config import Settings
from app.core.exceptions import register_exception_handlers
from app.db.session import engine, engine_options

SENSITIVE = "alice.secret@example.test"


def _failing_query_error() -> StatementError:
    options = {k: v for k, v in engine_options(Settings()).items() if k != "pool_pre_ping"}
    throwaway = create_engine("sqlite://", **options)
    try:
        with throwaway.connect() as connection:
            connection.execute(
                text("SELECT id FROM no_such_table WHERE email = :email"), {"email": SENSITIVE}
            )
    except DBAPIError as exc:
        return exc
    finally:
        throwaway.dispose()
    raise AssertionError("the query was expected to fail")


def test_the_application_engine_hides_parameters() -> None:
    assert engine.sync_engine.hide_parameters is True
    assert engine_options(Settings())["hide_parameters"] is True


def test_a_failed_querys_error_text_has_no_bound_values_but_keeps_its_context() -> None:
    error = _failing_query_error()
    rendered = "".join(traceback.format_exception(error))

    assert SENSITIVE not in rendered
    assert "hidden due to hide_parameters" in rendered  # SQLAlchemy's own placeholder
    assert "no_such_table" in rendered  # which statement failed is still there


def test_the_unhandled_exception_log_has_no_bound_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = _failing_query_error()
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise error

    with caplog.at_level(logging.DEBUG):
        response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert SENSITIVE not in response.text
    logged = caplog.text + "".join(
        "".join(traceback.format_exception(*r.exc_info)) for r in caplog.records if r.exc_info
    )
    assert SENSITIVE not in logged


def test_the_migration_engine_hides_parameters_too() -> None:
    source = (Path(__file__).parents[2] / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "hide_parameters=True" in source
