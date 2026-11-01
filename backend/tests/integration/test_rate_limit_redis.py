"""The shared rate limiter against a real Redis (AIGSEC-008): counts shared between limiter
instances (as between replicas), atomic under concurrency, scoped per user and organization, and
expiring.

Uses the TEST Redis only: the harness points REDIS_URL at database 15 (tests/isolation.py), which
this module checks before touching anything. Every key it writes lives under a prefix unique to
the test and is deleted afterwards. Skips when Redis is unreachable (fails under
AEGIS_REQUIRE_SERVICES=1, as in CI).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import redis.asyncio as redis_asyncio

from app.core.rate_limit import RateLimitBucket, RedisSlidingWindowRateLimiter
from app.db.redis import check_redis, redis_pool

from .requirements import service_unavailable

pytestmark = pytest.mark.integration

LLM = RateLimitBucket.LLM
TEST_REDIS_DB = 15


def _client() -> redis_asyncio.Redis:
    return redis_asyncio.Redis(connection_pool=redis_pool)


@pytest.fixture
async def prefix() -> AsyncIterator[str]:
    assert redis_pool.connection_kwargs.get("db") == TEST_REDIS_DB, "not the test Redis database"
    if not await check_redis(timeout=2.0):
        service_unavailable("Redis is not reachable — start the test Redis on localhost:6380")
    unique = f"aegisai-test:ratelimit:{uuid.uuid4().hex}"
    yield unique
    client = _client()
    try:
        keys = [key async for key in client.scan_iter(match=f"{unique}:*")]
        if keys:
            await client.delete(*keys)
    finally:
        await client.aclose()


def _limiter(prefix: str, *, limit: int, window: float = 60) -> RedisSlidingWindowRateLimiter:
    return RedisSlidingWindowRateLimiter(
        window_seconds=window,
        limits={LLM: limit},
        client_factory=_client,
        timeout_seconds=5.0,
        key_prefix=prefix,
    )


async def test_two_limiter_instances_share_one_budget(prefix: str) -> None:
    replica_a, replica_b = _limiter(prefix, limit=3), _limiter(prefix, limit=3)

    admitted = [
        await replica_a.check(LLM, "org:alice"),
        await replica_b.check(LLM, "org:alice"),
        await replica_a.check(LLM, "org:alice"),
    ]

    assert admitted == [None, None, None]
    # Switching replicas does not reset the count.
    assert (await replica_b.check(LLM, "org:alice") or 0) >= 1
    assert (await replica_a.check(LLM, "org:alice") or 0) >= 1


async def test_concurrent_requests_never_exceed_the_limit(prefix: str) -> None:
    replicas = [_limiter(prefix, limit=5) for _ in range(4)]

    results = await asyncio.gather(*(replicas[i % 4].check(LLM, "org:bob") for i in range(40)))

    assert sum(1 for r in results if r is None) == 5


async def test_users_and_organizations_have_separate_budgets(prefix: str) -> None:
    limiter = _limiter(prefix, limit=1)

    assert await limiter.check(LLM, "org-1:alice") is None
    assert await limiter.check(LLM, "org-1:alice") is not None  # alice is used up
    assert await limiter.check(LLM, "org-1:carol") is None  # another user is not
    assert await limiter.check(LLM, "org-2:alice") is None  # nor the same id elsewhere


async def test_the_window_expires_and_the_key_has_a_ttl(prefix: str) -> None:
    limiter = _limiter(prefix, limit=1, window=1)

    assert await limiter.check(LLM, "org:dave") is None
    retry = await limiter.check(LLM, "org:dave")
    assert retry == 1
    client = _client()
    try:
        ttl_ms = await client.pttl(limiter.redis_key(LLM, "org:dave"))
    finally:
        await client.aclose()
    assert 0 < ttl_ms <= 1000  # the key does not outlive its window

    await asyncio.sleep(1.2)
    assert await limiter.check(LLM, "org:dave") is None  # admitted again


async def test_a_refused_request_is_not_counted(prefix: str) -> None:
    limiter = _limiter(prefix, limit=2)
    for _ in range(2):
        await limiter.check(LLM, "org:erin")
    for _ in range(5):
        await limiter.check(LLM, "org:erin")  # refused, must not add entries

    client = _client()
    try:
        count = await client.zcard(limiter.redis_key(LLM, "org:erin"))
    finally:
        await client.aclose()
    assert count == 2
