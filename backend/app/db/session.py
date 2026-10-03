"""Async SQLAlchemy engine and session management for PostgreSQL."""

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=settings.debug)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_database(timeout: float = 2.0) -> bool:
    """Best-effort connectivity check used by the readiness endpoint."""
    try:
        async with asyncio.timeout(timeout), engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
