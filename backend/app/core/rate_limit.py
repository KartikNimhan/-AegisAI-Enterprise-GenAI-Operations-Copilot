"""Per-user rate limits for the expensive operations.

Three buckets, each a maximum number of admitted requests per user within a sliding window:

- ``llm``       — anything that calls the language model (chat, RAG, agents, multi-agent, and the
                  Research / Analyst agent task endpoints);
- ``upload``    — document uploads (validation, storage, extraction, chunking);
- ``embedding`` — embedding jobs (CPU-heavy, and synchronous in this release).

Limits come from settings (``RATE_LIMIT_*``); a limit of 0 switches that one bucket off, and
``RATE_LIMIT_ENABLED=false`` switches all of them off. Nothing here assumes a business threshold.

How it works, and what it does NOT do
-------------------------------------
- The limiter is keyed by the authenticated user id, applied only AFTER authentication (an
  anonymous request is refused with 401 before it can touch anyone's budget).
- Two backends (``RATE_LIMIT_BACKEND``, AIGSEC-008):

  - ``memory`` (the default, for local development): a sliding window held in this process. With
    several workers or replicas each keeps its own counts, so the effective limit is
    (limit x processes).
  - ``redis``: the same sliding window kept in Redis and shared by every worker and replica, so
    switching replicas does not reset anyone's budget. Each check is one Lua script, which Redis
    runs atomically, timed by the Redis server's clock (replicas need not agree on the time).
    Keys are ``aegisai:ratelimit:<bucket>:<sha256 of organization and user id>``: no token, no
    raw identifier. Every key expires one window after its last admitted request.

  Docker Compose and Kubernetes use ``redis``.
- A request that is admitted is counted even if it later fails; a refused request is not counted.
- One multi-agent request legitimately costs several ``llm`` admissions (the entry point plus each
  language-model-backed agent it calls over A2A with the caller's own token).

Fail closed
-----------
If the limiter cannot enforce its policy (an unexpected error, its table of tracked users is full
of live entries, or Redis is unreachable, slow, or rejects the credentials), the protected request
is refused with 503 rather than allowed through unmetered. Every bucket guards an expensive
operation (a model call, a document upload, an embedding job), so there is no fail-open fallback:
an outage of the shared store pauses those operations instead of letting them run unmetered.
Rate-limit responses carry a generic message and ``Retry-After``; they never include the limit
values, the caller's identifiers, or other users' usage.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import inspect
import math
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from functools import lru_cache
from typing import Annotated, Any, Protocol

import structlog
from fastapi import Depends, status

from app.core import audit
from app.core.exceptions import AppError, ServiceUnavailableError
from app.core.security import PrincipalDep
from app.dependencies import SettingsDep
from app.observability import metrics

logger = structlog.get_logger(__name__)


class RateLimitBucket(enum.StrEnum):
    LLM = "llm"
    UPLOAD = "upload"
    EMBEDDING = "embedding"


class RateLimitedError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "Too many requests. Please try again later.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


class RateLimiterFullError(Exception):
    """The tracking table is full of live entries; the limiter can no longer meter safely."""


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        window_seconds: float,
        limits: Mapping[RateLimitBucket, int],
        max_tracked_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = float(window_seconds)
        self._limits = dict(limits)
        self._max_tracked = max_tracked_keys
        self._clock = clock
        self._hits: dict[tuple[RateLimitBucket, str], deque[float]] = {}

    def limit_for(self, bucket: RateLimitBucket) -> int:
        return self._limits.get(bucket, 0)

    def check(self, bucket: RateLimitBucket, key: str) -> int | None:
        """Admits and counts the request (returns None), or returns the whole seconds until the
        caller may retry (and counts nothing). A bucket whose limit is 0 is unlimited."""
        limit = self.limit_for(bucket)
        if limit <= 0:
            return None
        now = self._clock()
        cutoff = now - self._window
        entry = self._hits.get((bucket, key))
        if entry is None:
            if len(self._hits) >= self._max_tracked:
                self._drop_expired(cutoff)
                if len(self._hits) >= self._max_tracked:
                    raise RateLimiterFullError
            entry = self._hits[(bucket, key)] = deque()
        while entry and entry[0] <= cutoff:
            entry.popleft()
        if len(entry) >= limit:
            return max(1, math.ceil(entry[0] + self._window - now))
        entry.append(now)
        return None

    def _drop_expired(self, cutoff: float) -> None:
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]


# One atomic sliding-window step. KEYS[1]: the counter; ARGV: window in ms, limit, a unique member.
# Returns 0 when the request is admitted (and counted), otherwise the whole seconds until a slot
# frees up (and counts nothing), matching `SlidingWindowRateLimiter.check`.
SLIDING_WINDOW_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
  if retry < 1 then retry = 1 end
  return retry
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""
REDIS_KEY_PREFIX = "aegisai:ratelimit"


class _RedisClient(Protocol):
    def register_script(self, script: str) -> Any: ...

    async def aclose(self) -> None: ...


class RedisSlidingWindowRateLimiter:
    """The shared limiter (AIGSEC-008). Same contract as `SlidingWindowRateLimiter.check`, but
    asynchronous; any Redis failure, and a reply slower than `timeout_seconds`, raises (the route
    dependency turns that into 503)."""

    def __init__(
        self,
        *,
        window_seconds: float,
        limits: Mapping[RateLimitBucket, int],
        client_factory: Callable[[], _RedisClient],
        timeout_seconds: float,
        key_prefix: str = REDIS_KEY_PREFIX,
    ) -> None:
        self._window_ms = int(window_seconds * 1000)
        self._limits = dict(limits)
        self._client_factory = client_factory
        self._timeout = timeout_seconds
        self._prefix = key_prefix

    def limit_for(self, bucket: RateLimitBucket) -> int:
        return self._limits.get(bucket, 0)

    def redis_key(self, bucket: RateLimitBucket, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return f"{self._prefix}:{bucket.value}:{digest}"

    async def check(self, bucket: RateLimitBucket, key: str) -> int | None:
        limit = self.limit_for(bucket)
        if limit <= 0:
            return None
        client = self._client_factory()
        try:
            async with asyncio.timeout(self._timeout):
                script = client.register_script(SLIDING_WINDOW_LUA)
                retry = int(
                    await script(
                        keys=[self.redis_key(bucket, key)],
                        args=[self._window_ms, limit, uuid.uuid4().hex],
                    )
                )
        finally:
            await client.aclose()
        return None if retry == 0 else max(1, retry)


def _redis_client() -> Any:
    from app.db.redis import redis, redis_pool

    return redis.Redis(connection_pool=redis_pool)


@lru_cache(maxsize=4)
def _cached_redis_limiter(
    window_seconds: int, llm: int, upload: int, embedding: int, timeout_seconds: float
) -> RedisSlidingWindowRateLimiter:
    return RedisSlidingWindowRateLimiter(
        window_seconds=window_seconds,
        limits={
            RateLimitBucket.LLM: llm,
            RateLimitBucket.UPLOAD: upload,
            RateLimitBucket.EMBEDDING: embedding,
        },
        client_factory=_redis_client,
        timeout_seconds=timeout_seconds,
    )


@lru_cache(maxsize=4)
def _cached_limiter(
    window_seconds: int, llm: int, upload: int, embedding: int, max_tracked_keys: int
) -> SlidingWindowRateLimiter:
    # Keyed on primitives (Settings is unhashable) so one limiter — hence one set of counters — is
    # shared by every request in this process.
    return SlidingWindowRateLimiter(
        window_seconds=window_seconds,
        limits={
            RateLimitBucket.LLM: llm,
            RateLimitBucket.UPLOAD: upload,
            RateLimitBucket.EMBEDDING: embedding,
        },
        max_tracked_keys=max_tracked_keys,
    )


def get_rate_limiter(
    settings: SettingsDep,
) -> SlidingWindowRateLimiter | RedisSlidingWindowRateLimiter:
    if settings.rate_limit_backend == "redis":
        return _cached_redis_limiter(
            settings.rate_limit_window_seconds,
            settings.rate_limit_llm_requests,
            settings.rate_limit_document_uploads,
            settings.rate_limit_embedding_jobs,
            settings.rate_limit_redis_timeout_seconds,
        )
    return _cached_limiter(
        settings.rate_limit_window_seconds,
        settings.rate_limit_llm_requests,
        settings.rate_limit_document_uploads,
        settings.rate_limit_embedding_jobs,
        settings.rate_limit_max_tracked_keys,
    )


RateLimiterDep = Annotated[
    SlidingWindowRateLimiter | RedisSlidingWindowRateLimiter, Depends(get_rate_limiter)
]


def rate_limited(bucket: RateLimitBucket) -> Callable[..., Awaitable[None]]:
    """A route dependency: ``@router.post(..., dependencies=[Depends(rate_limited(BUCKET))])``.

    It depends on the authenticated principal, so the router-level authentication always runs
    first. It is `async` on purpose: it then runs on the event loop, where the in-memory limiter's
    check-then-count has no await in it and so cannot interleave with another request (a sync
    dependency would run in a thread pool, where it could). The Redis limiter's check is one
    atomic script on the server, so it cannot interleave either.

    The counter is the caller's organization and user id together; the Redis limiter hashes it.
    """

    async def dependency(
        principal: PrincipalDep, settings: SettingsDep, limiter: RateLimiterDep
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        try:
            outcome = limiter.check(bucket, f"{principal.organization_id}:{principal.user_id}")
            retry_after = await outcome if inspect.isawaitable(outcome) else outcome
        except Exception as exc:  # noqa: BLE001 - fail closed on ANY limiter failure
            logger.error("rate_limit.unavailable", bucket=bucket.value, error=type(exc).__name__)
            metrics.record_rate_limiter_unavailable(bucket.value)
            raise ServiceUnavailableError() from exc
        if retry_after is not None:
            audit.record(
                "rate_limit.exceeded",
                actor=principal,
                resource_type="rate_limit",
                resource_id=bucket.value,
                outcome="limited",
            )
            metrics.record_rate_limit_refusal(bucket.value)
            raise RateLimitedError(retry_after)

    return dependency


# Ready-made dependencies for the route decorators: `dependencies=[LLM_RATE_LIMIT]`.
LLM_RATE_LIMIT = Depends(rate_limited(RateLimitBucket.LLM))
UPLOAD_RATE_LIMIT = Depends(rate_limited(RateLimitBucket.UPLOAD))
EMBEDDING_RATE_LIMIT = Depends(rate_limited(RateLimitBucket.EMBEDDING))
