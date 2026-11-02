"""Every CI job that runs tests against a database uses an isolated `_test` database.

The test suite takes its database from TEST_DATABASE_URL and refuses any name that does not end in
`_test` (backend/tests/isolation.py). These checks keep the workflows in step with that rule: a job
whose service database had another name would fail at the guard, and a job whose migration step
(DATABASE_URL) and tests (TEST_DATABASE_URL) named different databases would test an unmigrated one.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.engine import make_url

from tests.isolation import validate_database_url, validate_redis_url
from tests.unit.test_rag_integration_workflow import STEP_ENV_FORBIDDEN, database_redirections

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
# The jobs known to run the tests against a PostgreSQL service. A new one must be added here, so
# it is reviewed against the same rules.
EXPECTED_JOBS = {
    ("ci.yml", "test"),
    ("rag-integration.yml", "embeddings-and-rag"),
    ("rag-e2e-live.yml", "rag-end-to-end"),
}


def _jobs_with_a_postgres_service() -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in (workflow.get("jobs") or {}).items():
            if "postgres" in (job.get("services") or {}):
                found.append((path.name, name, job))
    return found


JOBS = _jobs_with_a_postgres_service()


def test_the_known_database_jobs_are_exactly_these() -> None:
    assert {(workflow, name) for workflow, name, _ in JOBS} == EXPECTED_JOBS


@pytest.mark.parametrize(("workflow", "name", "job"), JOBS, ids=[f"{w}:{n}" for w, n, _ in JOBS])
def test_the_service_database_is_a_test_database(
    workflow: str, name: str, job: dict[str, Any]
) -> None:
    postgres = job["services"]["postgres"]
    database = postgres["env"]["POSTGRES_DB"]

    assert database.endswith("_test")
    assert f"-d {database}" in postgres["options"]  # the health check waits for that database


@pytest.mark.parametrize(("workflow", "name", "job"), JOBS, ids=[f"{w}:{n}" for w, n, _ in JOBS])
def test_the_tests_and_the_migrations_use_that_same_database(
    workflow: str, name: str, job: dict[str, Any]
) -> None:
    env = job["env"]
    database = job["services"]["postgres"]["env"]["POSTGRES_DB"]

    # The same rules the test suite applies at start-up; "aegis" is the application default.
    parsed = validate_database_url(env["TEST_DATABASE_URL"], development_database="aegis")
    assert parsed.database == database
    assert env["DATABASE_URL"] == env["TEST_DATABASE_URL"]
    assert make_url(env["DATABASE_URL"]).database == database


@pytest.mark.parametrize(("workflow", "name", "job"), JOBS, ids=[f"{w}:{n}" for w, n, _ in JOBS])
def test_a_redis_service_is_reached_only_through_test_redis_url(
    workflow: str, name: str, job: dict[str, Any]
) -> None:
    env = job["env"]
    if "redis" not in job["services"]:
        assert "TEST_REDIS_URL" not in env
        return

    assert validate_redis_url(env["TEST_REDIS_URL"], development_redis_db=0) != 0
    assert "REDIS_URL" not in env  # the tests ignore it; one name avoids two diverging values


def test_no_workflow_sets_test_targets_outside_those_jobs() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert not STEP_ENV_FORBIDDEN & set(workflow.get("env") or {}), path.name
        for name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps", []):
                step_env = set(step.get("env") or {})
                assert not {"TEST_DATABASE_URL", "TEST_REDIS_URL"} & step_env, (path.name, name)
            if (path.name, name) not in EXPECTED_JOBS:
                # No other job may point anything at a database or Redis through its env either.
                assert not STEP_ENV_FORBIDDEN & set(job.get("env") or {}), (path.name, name)


# -- F7: the ci.yml test job gets the same redirection checks as the RAG workflows ---------------


def _ci() -> dict[Any, Any]:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _ci_pytest_step(workflow: dict[Any, Any]) -> dict[str, Any]:
    return next(s for s in workflow["jobs"]["test"]["steps"] if "pytest" in str(s.get("run", "")))


def test_no_step_in_ci_can_point_the_tests_at_another_database() -> None:
    assert database_redirections(_ci()) == []


_CI_MUTATIONS: dict[str, Callable[[dict[Any, Any]], None]] = {
    "step-env-DATABASE_URL": lambda w: (
        _ci_pytest_step(w)
        .setdefault("env", {})
        .update(DATABASE_URL="postgresql+asyncpg://u:p@localhost/aegis")
    ),
    "step-env-REDIS_URL": lambda w: (
        _ci_pytest_step(w).setdefault("env", {}).update(REDIS_URL="redis://localhost:6379/0")
    ),
    "step-env-TEST_DATABASE_URL": lambda w: (
        _ci_pytest_step(w)
        .setdefault("env", {})
        .update(TEST_DATABASE_URL="postgresql+asyncpg://u:p@localhost/other_test")
    ),
    "step-env-TEST_REDIS_URL": lambda w: (
        _ci_pytest_step(w).setdefault("env", {}).update(TEST_REDIS_URL="redis://localhost:6379/3")
    ),
    "migration-step-env": lambda w: (
        next(s for s in w["jobs"]["test"]["steps"] if "alembic" in str(s.get("run", "")))
        .setdefault("env", {})
        .update(DATABASE_URL="postgresql+asyncpg://u:p@localhost/aegis")
    ),
    "workflow-env": lambda w: w.setdefault("env", {}).update(
        TEST_DATABASE_URL="postgresql+asyncpg://u:p@localhost/other_test"
    ),
    "github-env-write": lambda w: w["jobs"]["test"]["steps"].insert(
        0, {"run": 'echo "TEST_DATABASE_URL=x" >> "$GITHUB_ENV"'}
    ),
    "github-path-write": lambda w: w["jobs"]["test"]["steps"].insert(
        0, {"run": 'echo "/opt/bin" >> "${GITHUB_PATH}"'}
    ),
    "other-job-step-env": lambda w: (
        w["jobs"]["lint"]["steps"][0]
        .setdefault("env", {})
        .update(DATABASE_URL="postgresql+asyncpg://u:p@localhost/aegis")
    ),
}


@pytest.mark.parametrize("mutation", list(_CI_MUTATIONS.values()), ids=list(_CI_MUTATIONS))
def test_the_ci_redirection_check_catches_future_overrides(
    mutation: Callable[[dict[Any, Any]], None],
) -> None:
    workflow = copy.deepcopy(_ci())
    mutation(workflow)

    assert database_redirections(workflow) != []
