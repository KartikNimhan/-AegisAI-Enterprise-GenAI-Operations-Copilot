"""Declarative base for SQLAlchemy ORM models.

Domain models (backend/app/domain/models) will inherit from `Base` once the
first persisted entities are introduced in a later milestone.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
