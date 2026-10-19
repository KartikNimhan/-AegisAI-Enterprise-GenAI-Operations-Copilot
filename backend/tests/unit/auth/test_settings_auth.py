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
def test_settings_load_outside_local_without_auth_so_migrations_and_scripts_still_run(
    environment: str,
) -> None:
    """Alembic (the Kubernetes migration Job, the compose `migrate` service) and
    the CLI scripts load Settings but never serve requests: they must not need
    authentication configured. Serving is gated separately."""
    settings = _settings(environment=environment)

    assert settings.auth_configured is False


@pytest.mark.parametrize("environment", ["docker", "kubernetes", "production"])
def test_serving_outside_local_fails_and_names_every_missing_variable(environment: str) -> None:
    with pytest.raises(ValueError) as info:
        _settings(environment=environment).validate_for_serving()

    message = str(info.value)
    assert "AUTH_ISSUER" in message
    assert "AUTH_AUDIENCE" in message
    assert "AUTH_JWKS_URL" in message


def test_serving_names_only_the_missing_variables() -> None:
    settings = _settings(
        environment="docker", auth_issuer=ISSUER, auth_jwks_url=JWKS, auth_audience=None
    )

    with pytest.raises(ValueError) as info:
        settings.validate_for_serving()

    message = str(info.value)
    assert "AUTH_AUDIENCE" in message
    assert "AUTH_ISSUER" not in message and "AUTH_JWKS_URL" not in message


def test_blank_values_count_as_unset() -> None:
    """docker-compose passes unset variables through as empty strings."""
    settings = _settings(environment="docker", auth_issuer="", auth_audience="", auth_jwks_url="  ")

    with pytest.raises(ValueError, match="AUTH_ISSUER"):
        settings.validate_for_serving()
    assert _settings(environment="local", auth_issuer="").auth_issuer is None


def test_a_fully_configured_non_local_environment_may_serve() -> None:
    settings = _configured(environment="docker")

    settings.validate_for_serving()  # does not raise
    assert settings.auth_configured is True


def test_local_development_may_serve_without_authentication() -> None:
    _settings(environment="local").validate_for_serving()  # does not raise


def test_the_application_refuses_to_be_built_outside_local_without_authentication() -> None:
    from app.main import create_app

    with pytest.raises(ValueError, match="AUTH_JWKS_URL"):
        create_app(_settings(environment="production"))


def test_debug_is_rejected_outside_local_development() -> None:
    with pytest.raises(ValidationError, match="DEBUG must be false"):
        _configured(environment="production", debug=True)

    assert _configured(environment="local", debug=True).debug is True


@pytest.mark.parametrize(
    ("environment", "debug", "expected"),
    [("local", True, True), ("local", False, False), ("production", False, False)],
)
def test_sql_echo_is_only_ever_enabled_in_local_development(
    environment: str, debug: bool, expected: bool
) -> None:
    assert _configured(environment=environment, debug=debug).sql_echo is expected


def test_the_production_code_default_for_the_session_engine_is_not_echoing() -> None:
    """`session.py` takes `echo` from `Settings.sql_echo`, never from DEBUG alone."""
    from pathlib import Path

    source = (Path(__file__).parents[3] / "app" / "db" / "session.py").read_text(encoding="utf-8")

    assert "echo=settings.sql_echo" in source
    assert "echo=settings.debug" not in source


def test_the_container_image_defaults_to_a_non_local_environment() -> None:
    """A container that forgets ENVIRONMENT must not inherit local-only settings."""
    from pathlib import Path

    dockerfile = (Path(__file__).parents[4] / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("AS runtime", 1)[1]

    assert "ENVIRONMENT=production" in runtime
    assert "DEBUG=false" in runtime


@pytest.mark.parametrize("cooldown", [-1, 61])
def test_the_failure_cooldown_is_bounded(cooldown: float) -> None:
    with pytest.raises(ValidationError, match="AUTH_JWKS_FAILURE_COOLDOWN_SECONDS"):
        _configured(auth_jwks_failure_cooldown_seconds=cooldown)


def test_the_failure_cooldown_can_be_disabled() -> None:
    assert _configured(auth_jwks_failure_cooldown_seconds=0).auth_jwks_failure_cooldown_seconds == 0


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://idp.example.test:0/realms/x",  # port zero
        "https://idp.example.test:99999/realms/x",  # out-of-range port
        "https://idp.example.test:abc/realms/x",  # unparsable port
        "https://[::1/realms/x",  # malformed IPv6
        "https://idp.example.test\\@evil.example/x",  # backslash
        "https://idp.example.test/real ms/x",  # whitespace
        "https://idp.example.test/x\n",  # control character
    ],
)
def test_malformed_auth_urls_are_rejected_at_load_time(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        _configured(auth_jwks_url=bad_url)


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
