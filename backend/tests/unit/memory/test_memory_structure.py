"""Structural guards for agent memory: every query is scoped, migration 0008 only adds one table
and matches the model, and the limits are validated at startup.

Offline: compiled SQL and Alembic's `--sql` rendering. Applying the migration to PostgreSQL is
tests/integration/test_ownership_migration.py (not run here).
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from alembic import command
from app.auth.scope import AccessScope
from app.config import Settings
from app.db.repositories.agent_memory_repository import AgentMemoryRepository
from app.domain.enums.memory_kind import MemoryKind, MemorySource
from app.domain.models.agent_memory import AgentMemory

BACKEND = Path(__file__).resolve().parents[3]
USER, ORG = uuid.uuid4(), uuid.uuid4()
SCOPE = AccessScope.for_user(user_id=USER, organization_id=ORG)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Result:
    rowcount = 0

    def scalar_one_or_none(self) -> None:
        return None

    def scalar_one(self) -> int:
        return 0

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result()

    def add(self, obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def delete(self, obj: Any) -> None:
        pass


async def test_every_memory_query_binds_the_owner_and_organization() -> None:
    session = _Session()
    repo = AgentMemoryRepository(session, SCOPE)  # type: ignore[arg-type]
    some_id = uuid.uuid4()

    await repo.get(some_id)
    await repo.get_by_hash("h")
    await repo.list_active(now=NOW, limit=5)
    await repo.count_active(now=NOW)
    await repo.delete(some_id)
    await repo.delete_all()
    await repo.delete_expired(now=NOW)

    assert len(session.statements) >= 7
    for statement in session.statements:
        values = list(statement.compile(dialect=postgresql.dialect()).params.values())
        assert USER in values and ORG in values, f"unscoped memory query:\n{statement}"


async def test_a_scope_without_an_owner_matches_nothing_and_cannot_create() -> None:
    nobody = AccessScope(user_id=None, organization_id=None)
    session = _Session()
    repo = AgentMemoryRepository(session, nobody)  # type: ignore[arg-type]

    await repo.get(uuid.uuid4())

    assert "false" in str(session.statements[0].compile(dialect=postgresql.dialect())).lower()
    with pytest.raises(ValueError):
        await repo.create(
            content="x",
            content_hash="h",
            kind=MemoryKind.FACT,
            source=MemorySource.AGENT,
            now=NOW,
            expires_at=NOW,
        )


def test_the_repository_has_no_way_to_name_an_owner() -> None:
    import inspect

    parameters = inspect.signature(AgentMemoryRepository.create).parameters

    assert not {"owner_user_id", "organization_id", "scope"} & set(parameters)


# -- migration 0008 -------------------------------------------------------------------


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.output_buffer = io.StringIO()
    return config


def _sql(direction: str, span: str) -> str:
    config = _config()
    (command.upgrade if direction == "up" else command.downgrade)(config, span, sql=True)
    return config.output_buffer.getvalue()  # type: ignore[union-attr]


def test_0008_only_creates_the_memory_table_and_its_index() -> None:
    sql = _sql("up", "0007:0008")
    statements = [s.strip() for s in re.sub(r"^--.*$", "", sql, flags=re.M).split(";") if s.strip()]

    for statement in statements:
        first = statement.splitlines()[0]
        assert (
            first in {"BEGIN", "COMMIT"}
            or first.startswith(("CREATE TABLE agent_memories", "CREATE INDEX"))
            or statement.startswith("UPDATE alembic_version SET version_num='0008'")
        ), statement
    assert not re.search(r"\b(DROP|TRUNCATE)\b|DELETE FROM|ALTER TABLE (?!agent_memories)", sql)


def test_0008_names_match_the_model() -> None:
    sql = _sql("up", "0007:0008")
    table: Any = AgentMemory.__table__
    declared = {c.name for c in table.constraints if c.name} | {
        i.name for i in table.indexes if i.name
    }

    assert declared  # the model really names its constraints and indexes
    for name in declared:
        assert name in sql, f"{name} is on the model but not in the migration"
    assert (
        "FOREIGN KEY(owner_user_id, organization_id) REFERENCES users (id, organization_id)" in sql
    )
    assert "ON DELETE RESTRICT" in sql
    for column in ("owner_user_id UUID NOT NULL", "organization_id UUID NOT NULL"):
        assert column in sql
    assert "expires_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql


def test_0008_columns_match_the_model() -> None:
    sql = _sql("up", "0007:0008")
    table = AgentMemory.__table__  # type: ignore[attr-defined]

    assert {c.name for c in table.columns} == {
        "id",
        "organization_id",
        "owner_user_id",
        "kind",
        "source",
        "content",
        "content_hash",
        "created_at",
        "updated_at",
        "expires_at",
    }
    for column in table.columns:
        assert re.search(rf"\b{column.name} ", sql), column.name


def test_0008_downgrade_drops_only_the_memory_table() -> None:
    sql = _sql("down", "0008:0007")

    assert "DROP TABLE agent_memories" in sql
    assert sql.count("DROP TABLE") == 1
    assert "conversations" not in sql and "documents" not in sql


# -- settings ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setting",
    [
        {"agent_memory_max_item_chars": 5},
        {"agent_memory_max_item_chars": 100_000},
        {"agent_memory_max_items_per_user": 0},
        {"agent_memory_max_writes_per_run": -1},
        {"agent_memory_max_recalled": 0},
        {"agent_memory_max_prompt_chars": 10},
        {"agent_memory_ttl_days": 0},
    ],
)
def test_nonsensical_memory_limits_stop_startup(setting: dict[str, int]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        Settings(**setting)  # type: ignore[arg-type]


def test_the_default_limits_are_valid_and_bounded() -> None:
    settings = Settings()

    assert settings.agent_memory_enabled is True
    assert settings.agent_memory_max_item_chars <= 2000  # the database CHECK's ceiling
    assert settings.agent_memory_max_recalled * settings.agent_memory_max_item_chars >= 1


def test_running_alembic_in_process_does_not_disable_the_applications_loggers() -> None:
    """Regression: env.py's logging config used to disable every existing logger, so any test
    that rendered migration SQL silenced logging (and the multi-agent observability test, which
    reads captured log records) for every test that ran after it."""
    import logging

    logger = logging.getLogger("app.multi_agent.orchestrator")
    logger.disabled = False

    _sql("up", "0007:0008")

    assert logger.disabled is False
