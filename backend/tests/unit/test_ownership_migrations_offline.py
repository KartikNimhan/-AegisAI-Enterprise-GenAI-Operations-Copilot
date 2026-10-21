"""Migrations 0006 and 0007, checked without a database.

Alembic's offline (`--sql`) mode renders the exact SQL a migration would run, so these tests
read what the migrations would do rather than trusting how they are written: they must only
add (never delete or rewrite data), the downgrade must only drop what 0006 added, the names
must match the ORM models, and 0007 must refuse to run while any row is unowned. Running them
against a real database (including upgrade, downgrade and re-upgrade) is
tests/integration/test_ownership_migration.py.
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from app.domain.models.conversation import Conversation
from app.domain.models.document import Document
from app.domain.models.user import User

BACKEND = Path(__file__).resolve().parents[2]


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.output_buffer = io.StringIO()
    return config


def _upgrade_sql(span: str) -> str:
    config = _config()
    command.upgrade(config, span, sql=True)
    return config.output_buffer.getvalue()  # type: ignore[union-attr]


def _downgrade_sql(span: str) -> str:
    config = _config()
    command.downgrade(config, span, sql=True)
    return config.output_buffer.getvalue()  # type: ignore[union-attr]


def _statements(sql: str) -> list[str]:
    cleaned = re.sub(r"^--.*$", "", sql, flags=re.MULTILINE)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def test_there_is_a_single_head_and_it_is_0007() -> None:
    assert ScriptDirectory.from_config(_config()).get_heads() == ["0007"]


def test_the_chain_continues_from_the_identity_migration() -> None:
    script = ScriptDirectory.from_config(_config())

    assert script.get_revision("0006").down_revision == "0005"
    assert script.get_revision("0007").down_revision == "0006"


def test_the_upgrade_only_adds_structure_and_never_touches_data() -> None:
    statements = _statements(_upgrade_sql("0005:0007"))

    for statement in statements:
        first_line = statement.splitlines()[0]
        allowed = (
            first_line in {"BEGIN", "COMMIT"}
            or first_line.startswith(("ALTER TABLE", "CREATE INDEX"))
            or statement.startswith("UPDATE alembic_version SET version_num=")
        )
        assert allowed, f"unexpected statement in the upgrade:\n{statement}"
    # ("ON DELETE RESTRICT" is a foreign-key rule, not a statement that deletes anything.)
    joined = "\n".join(statements)
    for forbidden in (r"\bDROP\b", r"\bDELETE FROM\b", r"\bTRUNCATE\b", r"\bINSERT\b"):
        assert not re.search(forbidden, joined), forbidden
    # The only UPDATEs are the version bookkeeping.
    assert [s for s in statements if s.startswith("UPDATE")] == [
        "UPDATE alembic_version SET version_num='0006' WHERE alembic_version.version_num = '0005'",
        "UPDATE alembic_version SET version_num='0007' WHERE alembic_version.version_num = '0006'",
    ]


def test_0006_adds_exactly_the_planned_columns_constraints_and_indexes() -> None:
    sql = _upgrade_sql("0005:0006")

    for fragment in (
        "ALTER TABLE users ADD CONSTRAINT uq_users_id_organization_id UNIQUE (id, organization_id)",
        "ALTER TABLE conversations ADD COLUMN organization_id UUID;",
        "ALTER TABLE conversations ADD COLUMN owner_user_id UUID;",
        "ALTER TABLE documents ADD COLUMN organization_id UUID;",
        "ALTER TABLE documents ADD COLUMN owner_user_id UUID;",
        "ALTER TABLE documents ADD COLUMN visibility VARCHAR(20) DEFAULT 'private' NOT NULL;",
        "CHECK (visibility IN ('private', 'organization'))",
        "FOREIGN KEY(owner_user_id, organization_id) REFERENCES users (id, organization_id) "
        "ON DELETE RESTRICT",
    ):
        assert fragment in sql, fragment
    # Owner columns are nullable here: making them required is the separate, guarded step 0007.
    assert "owner_user_id UUID NOT NULL" not in sql
    assert "organization_id UUID NOT NULL" not in sql


def test_0007_only_makes_the_owner_columns_required() -> None:
    statements = _statements(_upgrade_sql("0006:0007"))
    alters = [s for s in statements if s.startswith("ALTER TABLE")]

    assert sorted(alters) == sorted(
        f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL"
        for table in ("conversations", "documents")
        for column in ("owner_user_id", "organization_id")
    )


def test_the_downgrade_drops_only_what_0006_added_and_deletes_no_table() -> None:
    sql = _downgrade_sql("0006:0005")
    statements = [s for s in _statements(sql) if not s.startswith(("BEGIN", "COMMIT", "UPDATE"))]

    assert "DROP TABLE" not in sql and "DELETE" not in sql
    dropped_columns = sorted(s for s in statements if "DROP COLUMN" in s)
    assert dropped_columns == sorted(
        f"ALTER TABLE {table} DROP COLUMN {column}"
        for table in ("conversations", "documents")
        for column in ("owner_user_id", "organization_id")
    ) + ["ALTER TABLE documents DROP COLUMN visibility"]


def test_the_downgrade_of_0007_only_relaxes_the_requirement() -> None:
    statements = [
        s for s in _statements(_downgrade_sql("0007:0006")) if s.startswith("ALTER TABLE")
    ]

    assert statements and all("DROP NOT NULL" in s for s in statements)


OBJECT_NAMES = {
    "documents": {
        "fk_documents_owner_in_organization",
        "ck_documents_owner_and_organization_together",
        "ck_documents_visibility",
        "ix_documents_owner_user_id_checksum",
        "ix_documents_organization_id_visibility",
    },
    "conversations": {
        "fk_conversations_owner_in_organization",
        "ck_conversations_owner_and_organization_together",
        "ix_conversations_owner_user_id_updated_at",
    },
    "users": {"uq_users_id_organization_id"},
}
MODELS = {"documents": Document, "conversations": Conversation, "users": User}


@pytest.mark.parametrize("table", OBJECT_NAMES)
def test_the_models_declare_the_same_constraint_and_index_names_as_the_migration(
    table: str,
) -> None:
    sql = _upgrade_sql("0005:0006")
    model_table = MODELS[table].__table__  # type: ignore[attr-defined]
    declared = {c.name for c in model_table.constraints if c.name} | {
        i.name for i in model_table.indexes if i.name
    }

    for name in OBJECT_NAMES[table]:
        assert name in declared, f"{name} is in the migration but not on the model"
        assert name in sql, f"{name} is on the model but not in the migration"


# -- migration 0007's refusal --------------------------------------------------------


def _load_0007() -> Any:
    path = BACKEND / "alembic" / "versions" / "0007_require_ownership.py"
    spec = importlib.util.spec_from_file_location("aegisai_migration_0007", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Bind:
    def __init__(self, unowned: dict[str, int]) -> None:
        self._unowned = unowned
        self.queries: list[str] = []

    def execute(self, statement: Any) -> Any:
        sql = str(statement)
        self.queries.append(sql)
        table = "conversations" if "FROM conversations" in sql else "documents"
        return SimpleNamespace(scalar_one=lambda: self._unowned[table])


def _run_0007_upgrade(monkeypatch: pytest.MonkeyPatch, unowned: dict[str, int]) -> list[tuple]:
    module = _load_0007()
    altered: list[tuple] = []
    fake_op = SimpleNamespace(
        get_bind=lambda: _Bind(unowned),
        alter_column=lambda *args, **kwargs: altered.append((args, kwargs)),
    )
    monkeypatch.setattr(module, "op", fake_op)
    monkeypatch.setattr(module, "context", SimpleNamespace(is_offline_mode=lambda: False))
    module.upgrade()
    return altered


def test_0007_refuses_while_any_conversation_or_document_is_unowned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match=r"1 conversations.*scripts/assign_legacy_data.py"):
        _run_0007_upgrade(monkeypatch, {"conversations": 1, "documents": 0})


def test_0007_names_every_table_that_still_has_unowned_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match=r"2 conversations, 3 documents"):
        _run_0007_upgrade(monkeypatch, {"conversations": 2, "documents": 3})


def test_0007_alters_nothing_when_it_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_0007()
    altered: list[Any] = []
    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_bind=lambda: _Bind({"conversations": 0, "documents": 4}),
            alter_column=lambda *a, **k: altered.append((a, k)),
        ),
    )
    monkeypatch.setattr(module, "context", SimpleNamespace(is_offline_mode=lambda: False))

    with pytest.raises(RuntimeError):
        module.upgrade()

    assert altered == []


def test_0007_proceeds_when_every_row_is_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    altered = _run_0007_upgrade(monkeypatch, {"conversations": 0, "documents": 0})

    assert len(altered) == 4  # two columns on each of the two tables
    assert all(kwargs["nullable"] is False for _, kwargs in altered)
