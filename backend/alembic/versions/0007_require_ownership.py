"""require ownership (step 2 of 2: NOT NULL)

Makes `owner_user_id` and `organization_id` NOT NULL on `conversations` and
`documents`. Run it only after every existing row has an owner
(`scripts/assign_legacy_data.py`).

It refuses to run while any row is still unowned, with a message saying how many,
instead of failing later with a bare NOT NULL error. A refusal changes nothing
(Alembic runs this migration in one transaction), so `alembic upgrade head` on a
database that still has unassigned legacy rows simply stops here, at revision 0006.
On a database with no such rows (a fresh install) it passes straight through.

Downgrade only drops the NOT NULL requirement; it deletes and changes no rows.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("conversations", "documents")
_COLUMNS = ("owner_user_id", "organization_id")


def _refuse_if_any_row_is_unowned() -> None:
    if context.is_offline_mode():
        return  # `--sql` preview: there is no database to inspect
    bind = op.get_bind()
    unowned = {
        table: bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE owner_user_id IS NULL")  # noqa: S608
        ).scalar_one()
        for table in _TABLES
    }
    if any(unowned.values()):
        counts = ", ".join(f"{count} {table}" for table, count in unowned.items() if count)
        raise RuntimeError(
            f"Cannot require ownership yet: {counts} still have no owner. Assign them with "
            "`scripts/assign_legacy_data.py` (use --dry-run first), then run this migration again."
        )


def upgrade() -> None:
    _refuse_if_any_row_is_unowned()
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(table, column, existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(table, column, existing_type=sa.Uuid(), nullable=True)
