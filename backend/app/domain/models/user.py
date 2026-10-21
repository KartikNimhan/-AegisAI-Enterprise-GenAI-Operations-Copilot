"""Internal user persistence model.

Accounts are admin-created or invited; there is no self-service sign-up.
`role`, `is_active` and the organization come from this row on every
request — never from a token claim. Email uniqueness is case-insensitive
(a `lower(email)` unique index; the `citext` extension is not enabled in
this database).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums.user_role import UserRole

if TYPE_CHECKING:
    from app.domain.models.organization import Organization
    from app.domain.models.user_identity import UserIdentity


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Lets `documents` and `conversations` reference (id, organization_id) together, so the
        # database itself guarantees a row's owner belongs to the row's organization.
        UniqueConstraint("id", "organization_id", name="uq_users_id_organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="ck_users_role",
            native_enum=False,
            length=20,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=UserRole.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="users")
    identities: Mapped[list[UserIdentity]] = relationship(
        "UserIdentity", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


# Case-insensitive email uniqueness (defined after the class so the expression can
# reference the mapped column).
Index("uq_users_email_lower", func.lower(User.email), unique=True)
