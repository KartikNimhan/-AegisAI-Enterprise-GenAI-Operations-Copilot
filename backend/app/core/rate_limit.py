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
- It is an in-memory sliding window, so it is **per process**. With several workers or replicas
  each keeps its own counts, and the effective limit is (limit x processes). It is not shared
  through Redis or any other store. That is a real limitation for horizontally scaled
  deployments; see docs/operations/production-readiness.md.
- A request that is admitted is counted even if it later fails; a refused request is not counted.
- One multi-agent request legitimately costs several ``llm`` admissions (the entry point plus each
  language-model-backed agent it calls over A2A with the caller's own token).

Fail closed
-----------
If the limiter cannot enforce its policy (an unexpected error, or its table of tracked users is
full of live entries), the protected request is refused with 503 rather than allowed through
unmetered. Rate-limit responses carry a generic message and ``Retry-After``; they never include
the limit values, the caller's identifiers, or other users' usage.
"""

from __future__ import annotations

import enum
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import Depends, status

from app.core import audit
from app.core.exceptions import AppError, ServiceUnavailableError
from app.core.security import PrincipalDep
from app.dependencies import SettingsDep

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


def get_rate_limiter(settings: SettingsDep) -> SlidingWindowRateLimiter:
    return _cached_limiter(
        settings.rate_limit_window_seconds,
        settings.rate_limit_llm_requests,
        settings.rate_limit_document_uploads,
        settings.rate_limit_embedding_jobs,
        settings.rate_limit_max_tracked_keys,
    )


RateLimiterDep = Annotated[SlidingWindowRateLimiter, Depends(get_rate_limiter)]


def rate_limited(bucket: RateLimitBucket) -> Callable[..., Awaitable[None]]:
    """A route dependency: ``@router.post(..., dependencies=[Depends(rate_limited(BUCKET))])``.

    It depends on the authenticated principal, so the router-level authentication always runs
    first. It is `async` on purpose: it then runs on the event loop, where the limiter's
    check-then-count has no await in it and so cannot interleave with another request (a sync
    dependency would run in a thread pool, where it could).
    """

    async def dependency(
        principal: PrincipalDep, settings: SettingsDep, limiter: RateLimiterDep
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        try:
            retry_after = limiter.check(bucket, str(principal.user_id))
        except Exception as exc:  # noqa: BLE001 - fail closed on ANY limiter failure
            logger.error("rate_limit.unavailable", bucket=bucket.value, error=type(exc).__name__)
            raise ServiceUnavailableError() from exc
        if retry_after is not None:
            audit.record(
                "rate_limit.exceeded",
                actor=principal,
                resource_type="rate_limit",
                resource_id=bucket.value,
                outcome="limited",
            )
            raise RateLimitedError(retry_after)

    return dependency


# Ready-made dependencies for the route decorators: `dependencies=[LLM_RATE_LIMIT]`.
LLM_RATE_LIMIT = Depends(rate_limited(RateLimitBucket.LLM))
UPLOAD_RATE_LIMIT = Depends(rate_limited(RateLimitBucket.UPLOAD))
EMBEDDING_RATE_LIMIT = Depends(rate_limited(RateLimitBucket.EMBEDDING))
