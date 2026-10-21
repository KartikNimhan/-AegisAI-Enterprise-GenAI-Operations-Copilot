"""Static checks on docker-compose.yml.

Regression: services were built once and then reused by `docker compose up -d` /
`docker compose run`, so a running stack drifted from the code. The frontend image
still listened on the old port while Compose mapped and health-checked the new one
(the container stayed unhealthy), and a backend image from before the
authentication work kept serving unauthenticated, while `run migrate` could report
"nothing to do" because its own image predated migration 0005.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _services() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


def _building() -> list[str]:
    return sorted(name for name, service in _services().items() if "build" in service)


def test_there_are_locally_built_services_to_check() -> None:
    assert {"backend", "frontend", "migrate"} <= set(_building())


@pytest.mark.parametrize("name", _building())
def test_every_locally_built_service_is_always_rebuilt(name: str) -> None:
    assert _services()[name].get("pull_policy") == "build"


def test_the_migration_service_uses_the_same_build_as_the_backend() -> None:
    services = _services()

    assert services["migrate"]["build"] == services["backend"]["build"]


def test_the_backend_receives_every_authentication_setting_it_requires() -> None:
    environment = _services()["backend"]["environment"]

    for name in ("AUTH_ISSUER", "AUTH_AUDIENCE", "AUTH_JWKS_URL"):
        assert name in environment
