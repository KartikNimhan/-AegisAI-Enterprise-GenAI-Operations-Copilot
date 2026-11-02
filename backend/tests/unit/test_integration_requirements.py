"""CI must not go green when the services its integration tests need are missing.

The integration tests skip when Postgres or Redis is unreachable. CI provides both, and sets
AEGIS_REQUIRE_SERVICES=1 so that an unavailable service FAILS the run instead of quietly skipping
every isolation, repository and migration test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.integration.requirements import (
    REQUIRE_SERVICES_VAR,
    service_unavailable,
    services_required,
)

INTEGRATION = Path(__file__).resolve().parents[1] / "integration"
CI_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def test_without_the_flag_a_missing_service_is_a_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REQUIRE_SERVICES_VAR, raising=False)

    assert services_required() is False
    with pytest.raises(pytest.skip.Exception, match="Postgres is not reachable"):
        service_unavailable("Postgres is not reachable")


@pytest.mark.parametrize("value", ["0", "", "true", "yes"])
def test_only_the_value_1_requires_services(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(REQUIRE_SERVICES_VAR, value)

    assert services_required() is False


def test_with_the_flag_a_missing_service_fails_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REQUIRE_SERVICES_VAR, "1")

    with pytest.raises(pytest.fail.Exception, match="failure, not a skip"):
        service_unavailable("Postgres is not reachable")


def test_no_integration_test_skips_on_a_missing_service_by_itself() -> None:
    # Every infrastructure skip must go through `service_unavailable`, or CI could go green
    # without running it. Live-provider opt-ins use `pytest.mark.skipif`, which is fine.
    offenders = [
        path.name
        for path in INTEGRATION.glob("*.py")
        if path.name != "requirements.py"
        and re.search(r"\bpytest\.skip\(", path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_the_ci_test_job_requires_its_services_and_shows_skips() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["test"]

    assert str(job["env"][REQUIRE_SERVICES_VAR]) == "1"
    assert {"postgres", "redis"} <= set(job["services"])
    pytest_steps = [step["run"] for step in job["steps"] if "pytest" in str(step.get("run", ""))]
    assert pytest_steps and all("-rs" in step for step in pytest_steps)
