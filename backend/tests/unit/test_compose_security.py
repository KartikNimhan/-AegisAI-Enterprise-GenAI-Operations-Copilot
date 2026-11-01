"""Static security checks on docker-compose.yml (AIGSEC-002) and the Redis client's password
handling. Nothing is started: the file is parsed as YAML.

Before the fix, Compose published PostgreSQL and Redis on every network interface and Redis had no
password, so anyone on the same network could read and write it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr

from app.config import Settings
from app.db.redis import build_redis_pool

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _ROOT / "docker-compose.yml"
_DATABASE_PORTS = {"5432", "6379"}
DUMMY_PASSWORD = "not-a-real-password-just-a-test-value"


def _services() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


def _published(service: dict[str, Any]) -> list[str]:
    return [str(port) for port in service.get("ports", [])]


def _container_port(mapping: str) -> str:
    return mapping.rsplit(":", 1)[-1].split("/")[0]


@pytest.mark.parametrize(("name", "mapping"), [("postgres", "5433:5432"), ("redis", "6380:6379")])
def test_database_ports_are_published_on_loopback_only(name: str, mapping: str) -> None:
    assert _published(_services()[name]) == [f"127.0.0.1:{mapping}"]


def test_no_service_publishes_a_database_port_beyond_loopback() -> None:
    for name, service in _services().items():
        for mapping in _published(service):
            if _container_port(mapping) in _DATABASE_PORTS:
                assert mapping.startswith("127.0.0.1:"), (name, mapping)


def test_redis_requires_a_password_from_the_environment_never_a_literal() -> None:
    redis = _services()["redis"]
    script = redis["command"][-1]

    assert redis["environment"]["REDIS_PASSWORD"] == "${REDIS_PASSWORD:-}"
    assert 'if [ -z "$$REDIS_PASSWORD" ]' in script and "exit 1" in script  # fails closed
    assert "requirepass" in script
    # Not on the command line, where any process listing would show it.
    assert "--requirepass" not in script
    # Still started through the image's entrypoint, which drops to the unprivileged user.
    assert "exec docker-entrypoint.sh redis-server /tmp/redis.conf" in script


def test_the_redis_health_check_authenticates_without_exposing_the_password() -> None:
    test = _services()["redis"]["healthcheck"]["test"]

    assert test[0] == "CMD-SHELL"
    assert 'REDISCLI_AUTH="$$REDIS_PASSWORD"' in test[1]
    assert "grep -q PONG" in test[1]  # an authentication error is not "healthy"
    assert " -a " not in test[1]


def test_the_backend_gets_the_redis_password_separately_from_the_url() -> None:
    environment = _services()["backend"]["environment"]

    assert environment["REDIS_PASSWORD"] == "${REDIS_PASSWORD:-}"
    assert "@" not in environment["REDIS_URL"]  # no credentials inside the URL


def test_no_plaintext_redis_password_is_committed() -> None:
    text = _COMPOSE.read_text(encoding="utf-8")

    for line in text.splitlines():
        if "REDIS_PASSWORD:" in line:
            assert line.split("REDIS_PASSWORD:", 1)[1].strip() == "${REDIS_PASSWORD:-}"


# -- the client --------------------------------------------------------------------------


def test_without_a_password_the_client_connects_as_before() -> None:
    pool = build_redis_pool(Settings(redis_url="redis://localhost:6380/15"))

    assert pool.connection_kwargs.get("password") is None
    assert pool.connection_kwargs["db"] == 15


def test_with_a_password_the_client_authenticates_and_does_not_reveal_it() -> None:
    pool = build_redis_pool(
        Settings(redis_url="redis://localhost:6380/15", redis_password=SecretStr(DUMMY_PASSWORD))
    )

    assert pool.connection_kwargs["password"] == DUMMY_PASSWORD
    assert pool.connection_kwargs["db"] == 15  # the database number is untouched
    assert DUMMY_PASSWORD not in repr(pool)
    assert DUMMY_PASSWORD not in repr(pool.make_connection())


def test_an_empty_password_means_no_password() -> None:
    pool = build_redis_pool(Settings(redis_password=SecretStr("")))

    assert pool.connection_kwargs.get("password") is None


def test_the_password_setting_is_secret_in_settings_output() -> None:
    settings = Settings(redis_password=SecretStr(DUMMY_PASSWORD))

    assert DUMMY_PASSWORD not in repr(settings)
    assert DUMMY_PASSWORD not in str(settings.model_dump())


def test_compose_shares_rate_limits_through_redis() -> None:
    # AIGSEC-008: every backend process counts against one budget.
    assert _services()["backend"]["environment"]["RATE_LIMIT_BACKEND"] == (
        "${RATE_LIMIT_BACKEND:-redis}"
    )
