"""Settings: metrics are off by default; a token is required to serve them outside local."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import MIN_METRICS_TOKEN_CHARS, Settings

TOKEN = "t" * 32  # a clearly fake, test-only value
AUTH = {
    "auth_issuer": "https://idp.example.test/realms/x",
    "auth_audience": "aegisai-api",
    "auth_jwks_url": "https://idp.example.test/realms/x/certs",
}


def make(**overrides: object) -> Settings:
    """Settings that ignore any local .env file (its DEBUG=true would break non-local cases)."""
    return Settings(_env_file=None, debug=False, **overrides)  # type: ignore[call-arg,arg-type]


def test_metrics_are_off_by_default_with_no_token() -> None:
    settings = make()

    assert settings.metrics_enabled is False
    assert settings.metrics_token is None
    assert settings.metrics_token_configured is False


def test_the_token_is_a_secret_that_does_not_show_in_repr() -> None:
    settings = make(metrics_enabled=True, metrics_token=TOKEN)

    assert TOKEN not in repr(settings) and TOKEN not in str(settings.model_dump())
    assert settings.metrics_token_configured is True


@pytest.mark.parametrize("short", ["a", "x" * (MIN_METRICS_TOKEN_CHARS - 1)])
def test_a_set_token_must_not_be_trivially_short(short: str) -> None:
    with pytest.raises(ValidationError, match="METRICS_TOKEN"):
        make(metrics_enabled=True, metrics_token=short)


def test_outside_local_enabled_metrics_without_a_token_refuse_to_start() -> None:
    settings = make(environment="production", metrics_enabled=True, **AUTH)

    with pytest.raises(ValueError, match="METRICS_TOKEN"):
        settings.validate_for_serving()


def test_an_empty_token_counts_as_no_token() -> None:
    settings = make(
        environment="production",
        metrics_enabled=True,
        metrics_token="",
        **AUTH,
    )

    with pytest.raises(ValueError, match="METRICS_TOKEN"):
        settings.validate_for_serving()


def test_outside_local_a_token_allows_serving() -> None:
    make(
        environment="production",
        metrics_enabled=True,
        metrics_token=TOKEN,
        **AUTH,
    ).validate_for_serving()


def test_disabled_metrics_need_no_token_anywhere() -> None:
    make(environment="production", **AUTH).validate_for_serving()


def test_local_development_may_start_with_metrics_enabled_but_no_token() -> None:
    # The endpoint then answers 401 to everyone (see test_metrics_endpoint); it is never open.
    make(environment="local", metrics_enabled=True).validate_for_serving()


@pytest.mark.parametrize(
    "token",
    ["a" * 20 + "\n", " " + "a" * 20, "a" * 20 + " ", "a" * 20 + "\r\n", "\t" + "a" * 20],
)
def test_token_with_surrounding_whitespace_is_rejected(token: str) -> None:
    with pytest.raises(ValueError, match="whitespace"):
        Settings(_env_file=None, debug=False, metrics_token=token)  # type: ignore[call-arg]


@pytest.mark.parametrize("token", [" ", " " * 40, "\n", "\t\n "])
def test_a_whitespace_only_token_is_rejected(token: str) -> None:
    with pytest.raises(ValueError, match="whitespace"):
        Settings(_env_file=None, debug=False, metrics_token=token)  # type: ignore[call-arg]


def test_the_minimum_length_still_applies_to_a_clean_token() -> None:
    with pytest.raises(ValueError, match="at least"):
        Settings(_env_file=None, debug=False, metrics_token="short")  # type: ignore[call-arg]
    assert Settings(_env_file=None, debug=False, metrics_token="a" * MIN_METRICS_TOKEN_CHARS)  # type: ignore[call-arg]
