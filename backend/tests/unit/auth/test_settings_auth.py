"""Authentication settings: deliberate, documented startup behavior."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

ISSUER = "https://idp.example.test/realms/aegis"
JWKS = "https://idp.example.test/realms/aegis/protocol/openid-connect/certs"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


def _configured(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "auth_issuer": ISSUER,
        "auth_audience": "aegisai-api",
        "auth_jwks_url": JWKS,
    }
    values.update(overrides)
    return _settings(**values)


def test_local_development_may_leave_authentication_unconfigured() -> None:
    settings = _settings(environment="local")

    assert settings.auth_configured is False
    assert settings.auth_allowed_algorithms == ["RS256"]
    assert settings.auth_leeway_seconds == 30


@pytest.mark.parametrize("environment", ["docker", "kubernetes", "production"])
def test_outside_local_startup_fails_and_names_every_missing_variable(environment: str) -> None:
    with pytest.raises(ValidationError) as info:
        _settings(environment=environment)

    message = str(info.value)
    assert "AUTH_ISSUER" in message
    assert "AUTH_AUDIENCE" in message
    assert "AUTH_JWKS_URL" in message


def test_only_the_missing_variables_are_named() -> None:
    with pytest.raises(ValidationError) as info:
        _settings(environment="docker", auth_issuer=ISSUER, auth_jwks_url=JWKS, auth_audience=None)

    message = str(info.value)
    assert "AUTH_AUDIENCE" in message
    assert "AUTH_ISSUER," not in message and "set AUTH_ISSUER" not in message


def test_blank_values_count_as_unset() -> None:
    """docker-compose passes unset variables through as empty strings."""
    with pytest.raises(ValidationError, match="AUTH_ISSUER"):
        _settings(environment="docker", auth_issuer="", auth_audience="", auth_jwks_url="  ")

    assert _settings(environment="local", auth_issuer="").auth_issuer is None


def test_a_fully_configured_non_local_environment_starts() -> None:
    settings = _configured(environment="docker")

    assert settings.auth_configured is True


@pytest.mark.parametrize("field", ["auth_issuer", "auth_jwks_url"])
def test_plain_http_is_rejected_outside_local_unless_loopback(field: str) -> None:
    with pytest.raises(ValidationError, match="https"):
        _configured(environment="docker", **{field: "http://idp.internal.example.test/realms/x"})

    _configured(environment="docker", **{field: "http://localhost:18081/realms/x"})
    _configured(environment="docker", **{field: "http://127.0.0.1:18081/realms/x"})


def test_plain_http_is_allowed_in_local_development() -> None:
    settings = _configured(
        environment="local",
        auth_issuer="http://localhost:18081/realms/aegisai-demo",
        auth_jwks_url="http://localhost:18081/realms/aegisai-demo/protocol/openid-connect/certs",
    )

    assert settings.auth_configured is True


@pytest.mark.parametrize("bad", ["not a url", "ftp://idp.example.test/x", "https://"])
def test_malformed_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _configured(auth_issuer=bad)


@pytest.mark.parametrize("algorithms", [["HS256"], ["none"], ["RS256", "HS512"], []])
def test_only_asymmetric_algorithms_are_accepted(algorithms: list[str]) -> None:
    with pytest.raises(ValidationError, match="asymmetric"):
        _configured(auth_allowed_algorithms=algorithms)


def test_other_asymmetric_algorithms_can_be_enabled_explicitly() -> None:
    settings = _configured(auth_allowed_algorithms=["RS256", "ES256"])

    assert settings.auth_allowed_algorithms == ["RS256", "ES256"]


@pytest.mark.parametrize("leeway", [-1, 61, 3600])
def test_clock_leeway_is_bounded(leeway: int) -> None:
    with pytest.raises(ValidationError, match="AUTH_LEEWAY_SECONDS"):
        _configured(auth_leeway_seconds=leeway)


def test_forwarding_a_bearer_token_requires_https_agents_outside_local() -> None:
    with pytest.raises(ValidationError, match="TRUSTED_A2A_AGENTS"):
        _configured(
            environment="docker", trusted_a2a_agents=["http://agents.internal.example.test"]
        )

    _configured(environment="docker", trusted_a2a_agents=["https://agents.internal.example.test"])
    _configured(environment="docker", trusted_a2a_agents=["http://localhost:8000"])
