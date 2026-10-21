"""The sliding-window limiter and the settings that configure it (offline, with a fake clock)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.rate_limit import (
    RateLimitBucket,
    RateLimitedError,
    RateLimiterFullError,
    SlidingWindowRateLimiter,
    _cached_limiter,
    get_rate_limiter,
)

LLM, UPLOAD, EMBED = RateLimitBucket.LLM, RateLimitBucket.UPLOAD, RateLimitBucket.EMBEDDING


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def make(limits: dict[RateLimitBucket, int], *, window: float = 60.0, max_tracked: int = 1_000):
    clock = Clock()
    limiter = SlidingWindowRateLimiter(
        window_seconds=window, limits=limits, max_tracked_keys=max_tracked, clock=clock
    )
    return limiter, clock


# -- the window --------------------------------------------------------------------------


def test_requests_up_to_the_limit_are_admitted_and_the_next_one_is_refused() -> None:
    limiter, _ = make({LLM: 3})

    assert [limiter.check(LLM, "u") for _ in range(3)] == [None, None, None]
    assert limiter.check(LLM, "u") is not None


def test_a_refusal_says_how_long_to_wait_and_is_never_zero() -> None:
    limiter, clock = make({LLM: 2}, window=60)
    limiter.check(LLM, "u")
    clock.now += 10
    limiter.check(LLM, "u")
    clock.now += 5  # the first hit is 15 s old, so it leaves the window in 45 s

    assert limiter.check(LLM, "u") == 45

    clock.now += 44.5
    assert limiter.check(LLM, "u") == 1  # always at least one second


def test_the_window_slides_rather_than_resetting_all_at_once() -> None:
    limiter, clock = make({LLM: 2}, window=60)
    limiter.check(LLM, "u")  # t = 0
    clock.now += 30
    limiter.check(LLM, "u")  # t = 30
    clock.now += 31  # t = 61: the first hit has expired, the second has not

    assert limiter.check(LLM, "u") is None  # one slot is free again
    assert limiter.check(LLM, "u") is not None  # but only one


def test_refused_requests_are_not_counted_against_the_user() -> None:
    limiter, clock = make({LLM: 1}, window=60)
    limiter.check(LLM, "u")
    for _ in range(50):  # hammering while limited must not extend the penalty
        assert limiter.check(LLM, "u") is not None
    clock.now += 60

    assert limiter.check(LLM, "u") is None


def test_each_user_and_each_bucket_has_its_own_budget() -> None:
    limiter, _ = make({LLM: 1, UPLOAD: 1})

    assert limiter.check(LLM, "alice") is None
    assert limiter.check(LLM, "bob") is None  # another user
    assert limiter.check(UPLOAD, "alice") is None  # another bucket
    assert limiter.check(LLM, "alice") is not None


def test_a_limit_of_zero_means_that_bucket_is_unlimited() -> None:
    limiter, _ = make({LLM: 0, UPLOAD: 1})

    assert all(limiter.check(LLM, "u") is None for _ in range(1_000))
    assert limiter.check(UPLOAD, "u") is None and limiter.check(UPLOAD, "u") is not None


def test_a_bucket_with_no_configured_limit_is_unlimited_not_an_error() -> None:
    limiter, _ = make({})

    assert limiter.check(EMBED, "u") is None


# -- memory is bounded, and the limiter fails closed -----------------------------------


def test_expired_entries_are_reclaimed_when_the_table_is_full() -> None:
    limiter, clock = make({LLM: 1}, window=60, max_tracked=2)
    limiter.check(LLM, "a")
    limiter.check(LLM, "b")
    clock.now += 61  # both have expired

    assert limiter.check(LLM, "c") is None  # made room instead of refusing


def test_a_table_full_of_live_entries_fails_closed_rather_than_going_unmetered() -> None:
    limiter, _ = make({LLM: 1}, window=60, max_tracked=2)
    limiter.check(LLM, "a")
    limiter.check(LLM, "b")

    with pytest.raises(RateLimiterFullError):
        limiter.check(LLM, "c")
    # users already tracked are still metered normally
    assert limiter.check(LLM, "a") is not None


def test_unlimited_buckets_never_consume_table_space() -> None:
    limiter, _ = make({LLM: 0}, max_tracked=1)

    for index in range(100):
        assert limiter.check(LLM, f"u{index}") is None


# -- the error a caller sees -----------------------------------------------------------


def test_the_429_is_generic_and_carries_retry_after() -> None:
    error = RateLimitedError(17)

    assert error.status_code == 429 and error.code == "rate_limited"
    assert error.headers == {"Retry-After": "17"}
    assert "17" not in error.message and "limit" not in error.message.lower()


def test_retry_after_is_at_least_one_second() -> None:
    assert RateLimitedError(0).headers == {"Retry-After": "1"}


# -- settings ----------------------------------------------------------------------------


def test_the_defaults_are_valid_and_every_bucket_is_configurable() -> None:
    settings = Settings(
        rate_limit_window_seconds=120,
        rate_limit_llm_requests=7,
        rate_limit_document_uploads=3,
        rate_limit_embedding_jobs=2,
    )

    assert (settings.rate_limit_llm_requests, settings.rate_limit_document_uploads) == (7, 3)
    assert settings.rate_limit_enabled is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"rate_limit_window_seconds": 0},
        {"rate_limit_window_seconds": 86_401},
        {"rate_limit_llm_requests": -1},
        {"rate_limit_document_uploads": 1_000_001},
        {"rate_limit_embedding_jobs": -5},
        {"rate_limit_max_tracked_keys": 10},
        {"rate_limit_max_tracked_keys": 10_000_001},
    ],
)
def test_nonsensical_limits_are_refused_at_startup_not_silently_ignored(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_zero_is_a_valid_per_bucket_limit() -> None:
    assert Settings(rate_limit_llm_requests=0).rate_limit_llm_requests == 0


def test_one_limiter_is_shared_per_configuration_so_counters_persist_across_requests() -> None:
    _cached_limiter.cache_clear()
    settings = Settings()

    first = get_rate_limiter(settings)
    second = get_rate_limiter(settings)
    different = get_rate_limiter(Settings(rate_limit_llm_requests=99))

    assert first is second
    assert different is not first
