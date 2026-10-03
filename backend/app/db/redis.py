"""Async Redis client management."""

import asyncio
from collections.abc import AsyncGenerator

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()

redis_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """FastAPI dependency that yields a request-scoped Redis client."""
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.aclose()


async def check_redis(timeout: float = 2.0) -> bool:
    """Best-effort connectivity check used by the readiness endpoint."""
    client = redis.Redis(connection_pool=redis_pool)
    try:
        async with asyncio.timeout(timeout):
            await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()
