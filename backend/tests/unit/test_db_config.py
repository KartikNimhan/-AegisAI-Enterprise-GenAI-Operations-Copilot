"""Tests for database/Redis configuration wiring (no live connection needed)."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import redis as redis_module
from app.db import session as session_module
from app.db.base import Base


def test_engine_is_configured_from_settings() -> None:
    assert isinstance(session_module.engine, AsyncEngine)
    assert session_module.engine.url.drivername == "postgresql+asyncpg"


def test_session_factory_produces_async_sessions() -> None:
    # Session creation is lazy and does not open a connection, so no live
    # database is required here.
    session = session_module.AsyncSessionLocal()
    assert isinstance(session, AsyncSession)


def test_declarative_base_metadata_exists() -> None:
    assert Base.metadata is not None


def test_redis_pool_is_configured_from_settings() -> None:
    assert redis_module.redis_pool is not None
    assert redis_module.redis_pool.connection_kwargs.get("decode_responses") is True
