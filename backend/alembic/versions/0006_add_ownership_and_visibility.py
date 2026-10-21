"""add ownership and document visibility (step 1 of 2: nullable columns)

Additive only: adds columns, one unique constraint, check constraints, composite
foreign keys and indexes. It runs no UPDATE, DELETE or DROP and touches no existing
row's data (existing documents, if any, get `visibility = 'private'` from the
column default).

- `users`: unique (id, organization_id), so the tables below can reference both
  together and the database itself guarantees a row's owner belongs to the row's
  organization.
- `conversations`, `documents`: `organization_id` and `owner_user_id`, both NULLABLE
  for now. A row with no owner matches no caller's access scope, so unassigned legacy
  rows are invisible to everyone, not exposed. Ownership is assigned by
  `scripts/assign_legacy_data.py` (a human chooses the owner); migration 0007 then
  makes the columns NOT NULL.
- `documents.visibility`: 'private' (default) or 'organization'.

Foreign keys use ON DELETE RESTRICT, like `users.organization_id`: a user or
organization that owns data cannot be deleted out from under it.

Downgrade drops the new columns, which DISCARDS the ownership assignments (and with
them the isolation they provide); it deletes no conversation, message or document.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_COLUMNS = ["owner_user_id", "organization_id"]
_USER_COLUMNS = ["id", "organization_id"]  # columns of `users` (the referent table)


def upgrade() -> None:
    op.create_unique_constraint("uq_users_id_organization_id", "users", ["id", "organization_id"])

    # -- conversations ---------------------------------------------------------
    op.add_column("conversations", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("conversations", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_conversations_owner_and_organization_together",
        "conversations",
        "(owner_user_id IS NULL) = (organization_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_conversations_owner_in_organization",
        "conversations",
        "users",
        _OWNER_COLUMNS,
        _USER_COLUMNS,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_conversations_owner_user_id_updated_at",
        "conversations",
        ["owner_user_id", "updated_at"],
    )

    # -- documents ---------------------------------------------------------------
    op.add_column("documents", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "visibility",
            sa.Enum(
                "private",
                "organization",
                name="ck_documents_visibility",
                native_enum=False,
                length=20,
                create_constraint=True,
            ),
            server_default="private",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_documents_owner_and_organization_together",
        "documents",
        "(owner_user_id IS NULL) = (organization_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_documents_owner_in_organization",
        "documents",
        "users",
        _OWNER_COLUMNS,
        _USER_COLUMNS,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_documents_owner_user_id_checksum", "documents", ["owner_user_id", "checksum"]
    )
    op.create_index(
        "ix_documents_organization_id_visibility", "documents", ["organization_id", "visibility"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_organization_id_visibility", table_name="documents")
    op.drop_index("ix_documents_owner_user_id_checksum", table_name="documents")
    op.drop_constraint("fk_documents_owner_in_organization", "documents", type_="foreignkey")
    op.drop_constraint("ck_documents_owner_and_organization_together", "documents", type_="check")
    op.drop_column("documents", "visibility")
    op.drop_column("documents", "owner_user_id")
    op.drop_column("documents", "organization_id")

    op.drop_index("ix_conversations_owner_user_id_updated_at", table_name="conversations")
    op.drop_constraint(
        "fk_conversations_owner_in_organization", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_conversations_owner_and_organization_together", "conversations", type_="check"
    )
    op.drop_column("conversations", "owner_user_id")
    op.drop_column("conversations", "organization_id")

    op.drop_constraint("uq_users_id_organization_id", "users", type_="unique")
