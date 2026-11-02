"""The Redis-backed rate limiter's wrapper logic (AIGSEC-008), offline with a fake client.

What needs a real Redis (the Lua script's atomicity, counts shared between limiter instances,
expiry) is proven in tests/integration/test_rate_limit_redis.py against the test database.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import structlog
from pydantic import ValidationError

from app.auth.principal import Principal
from app.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.rate_limit import (
    REDIS_KEY_PREFIX,
    RateLimitBucket,
    RateLimitedError,
    RedisSlidingWindowRateLimiter,
    SlidingWindowRateLimiter,
    get_rate_limiter,
    rate_limited,
)

from ..conftest import DEFAULT_TEST_PRINCIPAL

LLM = RateLimitBucket.LLM
FAKE_PASSWORD = "fake-password-for-a-test-only"


class FakeClient:
    """Stands in for `redis.asyncio.Redis`: records the script call and returns `reply`."""

    def __init__(self, reply: Any = 0, *, delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.closed = 0

    def register_script(self, script: str) -> Any:
        async def run(*, keys: list[str], args: list[Any]) -> Any:
            self.calls.append({"keys": keys, "args": args})
            if self.delay:
                await asyncio.sleep(self.delay)
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

        return run

    async def aclose(self) -> None:
        self.closed += 1


def limiter(client: FakeClient, *, llm: int = 5, timeout: float = 1.0) -> Any:
    return RedisSlidingWindowRateLimiter(
        window_seconds=60, limits={LLM: llm}, client_factory=lambda: client, timeout_seconds=timeout
    )


async def test_an_admitted_request_returns_none_and_closes_the_client() -> None:
    client = FakeClient(reply=0)

    assert await limiter(client).check(LLM, "org:user") is None
    (call,) = client.calls
    assert call["args"][:2] == [60_000, 5]  # window in ms, limit
    assert client.closed == 1


async def test_a_refused_request_returns_the_seconds_to_wait() -> None:
    assert await limiter(FakeClient(reply=7)).check(LLM, "org:user") == 7


async def test_a_bucket_with_limit_zero_never_touches_redis() -> None:
    client = FakeClient()

    assert await limiter(client, llm=0).check(LLM, "org:user") is None
    assert client.calls == []


def test_keys_carry_no_raw_identifier_and_separate_bucket_user_and_organization() -> None:
    redis_limiter = limiter(FakeClient())
    user, org, other_org = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    key = redis_limiter.redis_key(LLM, f"{org}:{user}")

    assert key.startswith(f"{REDIS_KEY_PREFIX}:llm:")
    assert user not in key and org not in key
    assert key == redis_limiter.redis_key(LLM, f"{org}:{user}")  # stable
    assert key != redis_limiter.redis_key(LLM, f"{other_org}:{user}")
    assert key != redis_limiter.redis_key(RateLimitBucket.UPLOAD, f"{org}:{user}")


async def test_each_call_uses_a_unique_member_so_concurrent_hits_are_not_merged() -> None:
    client = FakeClient()
    redis_limiter = limiter(client)

    await redis_limiter.check(LLM, "k")
    await redis_limiter.check(LLM, "k")

    assert client.calls[0]["args"][2] != client.calls[1]["args"][2]


# -- the route dependency: fail closed -----------------------------------------------------


async def _admit(redis_limiter: Any, principal: Principal = DEFAULT_TEST_PRINCIPAL) -> None:
    await rate_limited(LLM)(principal=principal, settings=Settings(), limiter=redis_limiter)


async def test_the_dependency_awaits_the_redis_limiter_and_refuses_with_retry_after() -> None:
    with pytest.raises(RateLimitedError) as refused:
        await _admit(limiter(FakeClient(reply=9)))

    assert refused.value.headers == {"Retry-After": "9"}


async def test_the_dependency_keys_by_organization_and_user() -> None:
    client = FakeClient()
    redis_limiter = limiter(client)

    await _admit(redis_limiter)

    expected = redis_limiter.redis_key(
        LLM, f"{DEFAULT_TEST_PRINCIPAL.organization_id}:{DEFAULT_TEST_PRINCIPAL.user_id}"
    )
    assert client.calls[0]["keys"] == [expected]


async def test_a_redis_failure_refuses_the_request_with_503_and_logs_no_detail() -> None:
    failure = ConnectionError(f"AUTH failed for password {FAKE_PASSWORD}")

    with structlog.testing.capture_logs() as logs, pytest.raises(ServiceUnavailableError):
        await _admit(limiter(FakeClient(reply=failure)))

    (entry,) = [e for e in logs if e["event"] == "rate_limit.unavailable"]
    assert entry["error"] == "ConnectionError"
    assert FAKE_PASSWORD not in repr(logs)


async def test_a_slow_redis_refuses_the_request_with_503() -> None:
    client = FakeClient(reply=0, delay=0.5)

    with pytest.raises(ServiceUnavailableError):
        await _admit(limiter(client, timeout=0.05))
    assert client.closed == 1  # the client is still released


# -- selection and settings ----------------------------------------------------------------


def test_memory_stays_the_default_backend() -> None:
    assert isinstance(get_rate_limiter(Settings()), SlidingWindowRateLimiter)


def test_the_redis_backend_is_selected_by_setting() -> None:
    chosen = get_rate_limiter(Settings(rate_limit_backend="redis"))

    assert isinstance(chosen, RedisSlidingWindowRateLimiter)
    assert chosen is get_rate_limiter(Settings(rate_limit_backend="redis"))  # one per process


@pytest.mark.parametrize("value", [0.0, 0.01, 31])
def test_the_redis_timeout_is_bounded(value: float) -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_REDIS_TIMEOUT_SECONDS"):
        Settings(rate_limit_redis_timeout_seconds=value)


def test_an_unknown_backend_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(rate_limit_backend="memcached")  # type: ignore[arg-type]
