"""Runs the REAL memory repository and service against an in-memory SQLite database.

`AgentMemoryRepository` only awaits `execute`, `add`, `flush`, `delete` and (through the service)
`begin_nested`, so a thin async adapter over a synchronous SQLAlchemy session executes the exact
statements the application sends, including the ownership predicate, and returns real rows. That
proves the isolation and lifecycle rules by what comes back, not by inspecting query text.

What this does not prove: PostgreSQL specifics (the composite foreign key to `users`, the
`char_length` check being enforced by Postgres itself, concurrent writers). Those belong to the
database-backed tests in tests/integration/test_agent_memory.py, which have not been run here.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.scope import AccessScope
from app.config import Settings
from app.db.repositories.agent_memory_repository import AgentMemoryRepository
from app.domain.models.agent_memory import AgentMemory
from app.memory.service import AgentMemoryService

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def make_engine() -> Engine:
    # One shared connection: the HTTP test client runs the app on another thread.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _char_length(dbapi_connection: Any, _record: Any) -> None:
        # PostgreSQL's char_length(), used by the table's CHECK constraint.
        dbapi_connection.create_function("char_length", 1, lambda s: len(s) if s else 0)

    AgentMemory.__table__.create(engine)  # type: ignore[attr-defined]
    return engine


class _Savepoint:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._nested: Any = None

    async def __aenter__(self) -> _Savepoint:
        self._nested = self._session.begin_nested()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self._nested.commit()
        else:
            self._nested.rollback()


class AsyncSessionAdapter:
    """Just enough of AsyncSession for the memory code."""

    def __init__(self, session: Session) -> None:
        self.sync = session
        self.fail_next_execute: Exception | None = None
        # When set, only a statement whose SQL starts with this word (e.g. "DELETE") fails.
        self.fail_only_statements_starting: str | None = None

    async def execute(self, statement: Any) -> Any:
        if self.fail_next_execute is not None and (
            self.fail_only_statements_starting is None
            or str(statement).lstrip().upper().startswith(self.fail_only_statements_starting)
        ):
            error, self.fail_next_execute = self.fail_next_execute, None
            raise error
        return self.sync.execute(statement)

    def add(self, obj: Any) -> None:
        self.sync.add(obj)

    async def flush(self) -> None:
        self.sync.flush()

    async def delete(self, obj: Any) -> None:
        self.sync.delete(obj)

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self.sync)


def make_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class Person:
    def __init__(self, organization_id: uuid.UUID | None = None, is_admin: bool = False) -> None:
        self.user_id = uuid.uuid4()
        self.organization_id = organization_id or uuid.uuid4()
        self.scope = AccessScope.for_user(
            user_id=self.user_id, organization_id=self.organization_id, is_admin=is_admin
        )


class World:
    """One database, any number of people, each with their own service over the same session."""

    def __init__(self, **settings: object) -> None:
        self.engine = make_engine()
        self.session = Session(self.engine)
        self.adapter = AsyncSessionAdapter(self.session)
        self.settings = make_settings(**settings)
        self.now = NOW

    def service(
        self, person: Person, *, clock: Callable[[], datetime] | None = None
    ) -> AgentMemoryService:
        return AgentMemoryService(
            session=self.adapter,  # type: ignore[arg-type]
            repository=AgentMemoryRepository(self.adapter, person.scope),  # type: ignore[arg-type]
            settings=self.settings,
            clock=clock or (lambda: self.now),
        )

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()
