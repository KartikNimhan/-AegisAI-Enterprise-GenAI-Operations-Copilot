"""Async Redis client management."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis

from app.config import Settings, get_settings

settings = get_settings()


def build_redis_pool(settings: Settings) -> redis.ConnectionPool:
    """The connection pool for `settings.redis_url`, authenticating with `REDIS_PASSWORD` when it
    is set. The password is passed to the client directly, never written into the URL, so it
    never appears in a logged URL; redis-py does not include it in a connection's repr either."""
    options: dict[str, Any] = {"decode_responses": True}
    if settings.redis_password is not None and settings.redis_password.get_secret_value():
        options["password"] = settings.redis_password.get_secret_value()
    return redis.ConnectionPool.from_url(settings.redis_url, **options)


redis_pool = build_redis_pool(settings)


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """FastAPI dependency that yields a request-scoped Redis client."""
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.aclose()


async def check_redis(timeout: float = 2.0) -> bool:
    """Best-effort connectivity check used by the readiness endpoint. Any failure, including a
    wrong or missing password, is just "unavailable": the error itself is never surfaced."""
    client = redis.Redis(connection_pool=redis_pool)
    try:
        async with asyncio.timeout(timeout):
            await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()
