"""Migration 0009 (`message_citations`, M10.4 T3) and its model, checked without a database.

Alembic's offline (`sql=True`) mode renders the exact SQL the migration would run without opening a
connection (the unit-test conftest also refuses any PostgreSQL connection). These tests read that
SQL rather than trusting how the migration is written: it must create exactly one table and touch
nothing else, its constraints must be the approved ones and match the ORM model, it must have a
foreign key to `messages` only (never to documents or chunks), and its downgrade must drop only
that table. Applying it to a real database is NOT done here (owner approval required).
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint

from alembic import command
from app.db.base import Base
from app.domain import models
from app.domain.models import message_citation
from app.domain.models.message import Message
from app.domain.models.message_citation import MessageCitation

BACKEND = Path(__file__).resolve().parents[2]
TABLE = "message_citations"
EXPECTED_COLUMNS = {
    "id": "UUID NOT NULL",
    "message_id": "UUID NOT NULL",
    "source_id": "VARCHAR(16) NOT NULL",
    "position": "SMALLINT NOT NULL",
    "document_id": "UUID NOT NULL",
    "chunk_id": "UUID NOT NULL",
    "similarity": "DOUBLE PRECISION NOT NULL",
    "cited": "BOOLEAN NOT NULL",
    "passage_chars": "INTEGER NOT NULL",
    "passage_truncated": "BOOLEAN NOT NULL",
    "rendering_version": "VARCHAR(32) NOT NULL",
    "passage_sha256": "CHAR(64) NOT NULL",
    "created_at": "TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
}
VERSION_UPDATE = (
    "UPDATE alembic_version SET version_num='0009' WHERE alembic_version.version_num = '0008'"
)
EXPECTED_CHECKS = {
    "ck_message_citations_source_id_format": "source_id ~ '^S[1-9][0-9]{0,2}$'",
    "ck_message_citations_source_id_position": """source_id = 'S' || "position"::text""",
    "ck_message_citations_position_positive": '"position" > 0',
    "ck_message_citations_passage_chars": "passage_chars >= 0",
    "ck_message_citations_passage_sha256": "passage_sha256 ~ '^[0-9a-f]{64}$'",
    "ck_message_citations_rendering_version": "char_length(rendering_version) > 0",
    "ck_message_citations_similarity": "similarity BETWEEN -1.0 AND 1.0",
}


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.output_buffer = io.StringIO()
    return config


def _sql(direction: str, span: str) -> str:
    config = _config()
    (command.upgrade if direction == "up" else command.downgrade)(config, span, sql=True)
    return config.output_buffer.getvalue()  # type: ignore[union-attr]


def _statements(sql: str) -> list[str]:
    cleaned = re.sub(r"^--.*$", "", sql, flags=re.MULTILINE)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


@pytest.fixture(scope="module")
def upgrade_sql() -> str:
    return _sql("up", "0008:0009")


@pytest.fixture(scope="module")
def create_table(upgrade_sql: str) -> str:
    (statement,) = [s for s in _statements(upgrade_sql) if s.startswith("CREATE TABLE")]
    return statement


def _table() -> Any:
    return MessageCitation.__table__


# -- the chain -----------------------------------------------------------------------------------


def test_there_is_a_single_head_and_it_is_0009() -> None:
    assert ScriptDirectory.from_config(_config()).get_heads() == ["0009"]


def test_0009_descends_from_0008() -> None:
    assert ScriptDirectory.from_config(_config()).get_revision("0009").down_revision == "0008"


# -- the upgrade ---------------------------------------------------------------------------------


def test_the_upgrade_creates_only_the_citation_table(upgrade_sql: str) -> None:
    for statement in _statements(upgrade_sql):
        first_line = statement.splitlines()[0]
        assert (
            first_line in {"BEGIN", "COMMIT"}
            or first_line.startswith(f"CREATE TABLE {TABLE} (")
            or statement == VERSION_UPDATE
        ), f"unexpected statement in the upgrade:\n{statement}"
    assert upgrade_sql.count("CREATE TABLE") == 1


def test_the_upgrade_changes_no_existing_table_and_backfills_nothing(upgrade_sql: str) -> None:
    for forbidden in (
        r"\bDROP\b",
        r"\bALTER\b",
        r"\bDELETE FROM\b",
        r"\bTRUNCATE\b",
        r"\bINSERT\b",
        r"\bCREATE INDEX\b",  # the unique constraint already indexes (message_id, source_id)
    ):
        assert not re.search(forbidden, upgrade_sql), forbidden
    updates = [s for s in _statements(upgrade_sql) if s.startswith("UPDATE")]
    assert updates == [VERSION_UPDATE]


@pytest.mark.parametrize(("column", "definition"), EXPECTED_COLUMNS.items())
def test_every_column_has_the_approved_type_and_is_required(
    create_table: str, column: str, definition: str
) -> None:
    assert f"    {column} {definition}," in create_table


def test_the_table_has_exactly_the_approved_columns(create_table: str) -> None:
    column_lines = [
        line.strip()
        for line in create_table.splitlines()[1:]
        if not line.strip().startswith(("CONSTRAINT", ")"))
    ]
    assert [line.split()[0] for line in column_lines] == list(EXPECTED_COLUMNS)


def test_the_only_foreign_key_is_to_messages_and_cascades(create_table: str) -> None:
    assert create_table.count("FOREIGN KEY") == 1
    assert create_table.count("REFERENCES") == 1
    assert (
        "CONSTRAINT fk_message_citations_message_id FOREIGN KEY(message_id) "
        "REFERENCES messages (id) ON DELETE CASCADE"
    ) in create_table


def test_documents_and_chunks_are_referenced_without_foreign_keys(create_table: str) -> None:
    for referenced in ("documents", "document_chunks", "chunk_embeddings"):
        assert f"REFERENCES {referenced}" not in create_table
    assert "FOREIGN KEY(document_id" not in create_table
    assert "FOREIGN KEY(chunk_id" not in create_table


def test_the_only_unique_constraint_is_message_and_source_id(create_table: str) -> None:
    assert create_table.count("UNIQUE") == 1
    assert (
        "CONSTRAINT uq_message_citations_message_source UNIQUE (message_id, source_id)"
        in create_table
    )
    # Deliberately no (message_id, position) constraint: see test_position_and_source_id_agree.
    assert "UNIQUE (message_id, position)" not in create_table


def test_the_primary_key_is_the_id(create_table: str) -> None:
    assert "CONSTRAINT pk_message_citations PRIMARY KEY (id)" in create_table


@pytest.mark.parametrize(("name", "expression"), EXPECTED_CHECKS.items())
def test_every_approved_check_is_present(create_table: str, name: str, expression: str) -> None:
    assert f"CONSTRAINT {name} CHECK ({expression})" in create_table


def test_there_are_no_other_checks(create_table: str) -> None:
    assert create_table.count("CHECK (") == len(EXPECTED_CHECKS)


# -- the downgrade -------------------------------------------------------------------------------


def test_the_downgrade_drops_only_the_citation_table() -> None:
    statements = _statements(_sql("down", "0009:0008"))

    assert [s for s in statements if s not in {"BEGIN", "COMMIT"}] == [
        f"DROP TABLE {TABLE}",
        "UPDATE alembic_version SET version_num='0008' WHERE alembic_version.version_num = '0009'",
    ]


# -- the model agrees with the migration ---------------------------------------------------------


def test_the_model_declares_the_same_named_constraints_as_the_migration(create_table: str) -> None:
    declared = {c.name for c in _table().constraints if c.name}
    in_sql = set(re.findall(r"CONSTRAINT (\w+) ", create_table))

    assert declared == in_sql
    assert len(in_sql) == 1 + 1 + 1 + len(EXPECTED_CHECKS)  # primary key, foreign key, unique


def test_the_models_check_expressions_are_the_migrations() -> None:
    model_checks = {
        c.name: str(c.sqltext) for c in _table().constraints if isinstance(c, CheckConstraint)
    }
    assert model_checks == EXPECTED_CHECKS


def test_the_model_has_exactly_the_approved_columns_all_required() -> None:
    table = _table()

    assert [c.name for c in table.columns] == list(EXPECTED_COLUMNS)
    assert all(not c.nullable for c in table.columns)
    assert [c.name for c in table.primary_key.columns] == ["id"]


def test_the_model_has_a_foreign_key_to_messages_only() -> None:
    foreign_keys = list(_table().foreign_keys)

    assert len(foreign_keys) == 1
    (fk,) = foreign_keys
    assert fk.parent.name == "message_id"
    assert fk.target_fullname == "messages.id"
    assert fk.ondelete == "CASCADE"
    assert not _table().c.document_id.foreign_keys
    assert not _table().c.chunk_id.foreign_keys


def test_no_orm_relationship_adds_cascades_or_lazy_loading() -> None:
    assert not MessageCitation.__mapper__.relationships
    assert "citations" not in Message.__mapper__.relationships


def test_the_model_is_registered_for_metadata_and_alembic() -> None:
    assert Base.metadata.tables[TABLE] is _table()
    assert models.MessageCitation is MessageCitation
    env = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "MessageCitation" in env


# -- what the checks accept (the same regular expressions, evaluated here) -----------------------


def _pattern(check: str) -> re.Pattern[str]:
    match = re.search(r"~ '(.+)'$", check)
    assert match, check
    return re.compile(match.group(1))


@pytest.mark.parametrize("source_id", ["S1", "S9", "S10", "S20", "S99", "S100", "S999"])
def test_the_source_id_check_accepts_s1_to_s999(source_id: str) -> None:
    assert _pattern(message_citation.SOURCE_ID_FORMAT_CHECK).fullmatch(source_id)


@pytest.mark.parametrize(
    "source_id", ["S0", "S01", "S1000", "s1", "S", "1", "S-1", "S1 ", " S1", "SOURCE 1", "S１"]
)
def test_the_source_id_check_rejects_everything_else(source_id: str) -> None:
    assert not _pattern(message_citation.SOURCE_ID_FORMAT_CHECK).fullmatch(source_id)


def test_position_and_source_id_agree() -> None:
    """`source_id = 'S' || position` with `position > 0` maps each position to exactly one id and
    back (a positive integer's text has no sign or leading zero), so UNIQUE (message_id,
    source_id) already makes (message_id, position) unique. Positions 1..999 are the ones whose
    id passes the format check."""
    pattern = _pattern(message_citation.SOURCE_ID_FORMAT_CHECK)
    ids = [f"S{position}" for position in range(1, 1000)]

    assert all(pattern.fullmatch(i) for i in ids)
    assert len(set(ids)) == len(ids)
    assert not pattern.fullmatch("S1000")


@pytest.mark.parametrize("digest", ["0" * 64, "a" * 64, "0123456789abcdef" * 4])
def test_the_sha256_check_accepts_64_lowercase_hex_characters(digest: str) -> None:
    assert _pattern(message_citation.SHA256_CHECK).fullmatch(digest)


@pytest.mark.parametrize("digest", ["A" * 64, "0" * 63, "0" * 65, "g" * 64, "", "0" * 63 + " "])
def test_the_sha256_check_rejects_anything_else(digest: str) -> None:
    assert not _pattern(message_citation.SHA256_CHECK).fullmatch(digest)


def test_the_similarity_check_is_the_inclusive_approved_range() -> None:
    # Owner decision 2026-11-03 (Option A): [-1.0, 1.0], inclusive. The T4 writer must reject
    # NaN and +/-infinity and clamp finite values into this range before saving.
    assert message_citation.SIMILARITY_CHECK == "similarity BETWEEN -1.0 AND 1.0"
