"""Offline checks for the approval-gated live-LLM RAG workflow (`rag-e2e-live.yml`).

It is the only workflow that may receive an LLM key, so these checks are about containing it:
started by hand only; one job, in the `groq-live` GitHub Environment (whose required reviewer
approves every run); exactly one secret expression, `secrets.GROQ_API_KEY`, used only on the single
pytest step; no job token in the checkout or in any expression; the job's own disposable database;
nothing that turns a failure into a pass; exactly the live test file; and a final check that fails
the job when the tests were skipped, for example because the secret is missing. The no-secrets
retrieval workflow and ordinary CI must stay separate and secret-free.

The generic detectors come from test_rag_integration_workflow.py, where they are also run on
hand-made positive and negative examples. None of this runs the workflow; the first approved
manual run does that.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.test_rag_integration_workflow import (
    database_redirections,
    secret_or_token_expressions,
)

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOWS / "rag-e2e-live.yml"
LIVE_TEST = "backend/tests/integration/test_rag_end_to_end_live.py"
JOB = "rag-end-to-end"
ENVIRONMENT = "groq-live"
ONLY_SECRET = "secrets.GROQ_API_KEY"
PYTEST_STEP_ID = "tests"
CHECK_STEP_NAME = "Fail unless every live test ran and passed"
CHECK_STEP_IF = "${{ !cancelled() }}"
USES = re.compile(r"^\s*(?:- )?uses:\s*([\w.-]+/[\w./-]+)@(\S+)(.*)$", re.MULTILINE)
EXPECTED_PYTEST_ARGV = [
    *("uv", "run", "pytest", "-v", "-rs", "-p", "no:cacheprovider"),
    "--junitxml=rag-e2e-live-junit.xml",
    LIVE_TEST,
]


@pytest.fixture(scope="module")
def raw() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(raw: str) -> dict[Any, Any]:
    return yaml.safe_load(raw)


@pytest.fixture(scope="module")
def job(workflow: dict[Any, Any]) -> dict[str, Any]:
    return workflow["jobs"][JOB]


def _pytest_step(job: dict[str, Any]) -> dict[str, Any]:
    steps = [s for s in job["steps"] if "uv run pytest" in str(s.get("run", ""))]
    assert len(steps) == 1, f"expected exactly one pytest step, found {len(steps)}"
    return steps[0]


def _check_step(job: dict[str, Any]) -> dict[str, Any]:
    steps = [s for s in job["steps"] if s.get("name") == CHECK_STEP_NAME]
    assert len(steps) == 1, f"expected exactly one {CHECK_STEP_NAME!r} step, found {len(steps)}"
    return steps[0]


def _live_test_count() -> int:
    tree = ast.parse((ROOT / LIVE_TEST).read_text(encoding="utf-8"))
    return sum(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_")
        for node in tree.body
    )


def failure_neutralizers(workflow: dict[Any, Any]) -> list[str]:
    """`continue-on-error` anywhere, an `if:` on the job or on any step but the final check, or a
    different `if:` there: each could let a failed or skipped run pass."""
    found: list[str] = []
    for job_name, job in workflow["jobs"].items():
        found += [f"job {job_name}: {key}" for key in ("continue-on-error", "if") if key in job]
        for step in job.get("steps", []):
            label = f"{job_name} step {step.get('name') or step.get('uses') or step.get('run')!r}"
            if "continue-on-error" in step:
                found.append(f"{label}: continue-on-error")
            if step.get("name") == CHECK_STEP_NAME:
                if step.get("if") != CHECK_STEP_IF:
                    found.append(f"{label}: if is {step.get('if')!r}, not {CHECK_STEP_IF!r}")
            elif "if" in step:
                found.append(f"{label}: if {step['if']!r}")
    return found


# -- structure ---------------------------------------------------------------------------------


def test_it_runs_only_when_started_by_hand(workflow: dict[Any, Any]) -> None:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = workflow[True] if True in workflow else workflow["on"]

    assert set(triggers) == {"workflow_dispatch"}
    assert not (triggers["workflow_dispatch"] or {}).get("inputs")  # nothing reaches the shell


def test_the_token_is_read_only(workflow: dict[Any, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}, name


def test_the_checkout_does_not_keep_the_token(job: dict[str, Any]) -> None:
    checkouts = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]

    assert len(checkouts) == 1
    assert checkouts[0]["with"]["persist-credentials"] is False


def test_it_is_one_job_on_a_github_hosted_runner_with_a_timeout(
    workflow: dict[Any, Any], job: dict[str, Any]
) -> None:
    assert set(workflow["jobs"]) == {JOB}
    assert str(job["runs-on"]).startswith("ubuntu-")
    assert "self-hosted" not in str(job["runs-on"])
    assert 0 < int(job["timeout-minutes"]) <= 60
    assert workflow["concurrency"]["group"].startswith("rag-e2e-live-")


def test_every_action_is_the_commit_ci_already_pins(raw: str) -> None:
    pinned_by_ci = {
        action: ref
        for action, ref, _ in USES.findall((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    }
    uses = USES.findall(raw)

    assert uses
    for action, ref, rest in uses:
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{action}@{ref} is not pinned to a commit"
        assert re.search(r"#\s*v\d+\.\d+(\.\d+)?", rest), f"{action} has no version comment"
        assert pinned_by_ci.get(action) == ref, f"{action} is not pinned to ci.yml's commit"


def test_the_job_runs_in_the_approval_gated_environment(job: dict[str, Any]) -> None:
    environment = job["environment"]
    name = environment.get("name") if isinstance(environment, dict) else environment

    assert name == ENVIRONMENT


def test_the_only_secret_is_the_llm_key_and_only_the_pytest_step_receives_it(
    workflow: dict[Any, Any], job: dict[str, Any], raw: str
) -> None:
    assert secret_or_token_expressions(raw) == [ONLY_SECRET]  # once, and nothing else
    assert "GITHUB_TOKEN" not in raw
    assert _pytest_step(job).get("env") == {"GROQ_API_KEY": f"${{{{ {ONLY_SECRET} }}}}"}
    assert "GROQ_API_KEY" not in (workflow.get("env") or {})
    assert "GROQ_API_KEY" not in (job.get("env") or {})
    others = [s for s in job["steps"] if s is not _pytest_step(job)]
    assert all("GROQ_API_KEY" not in (s.get("env") or {}) for s in others)
    for name, each in workflow["jobs"].items():
        assert "secrets" not in each, name  # e.g. `secrets: inherit` on a reusable-workflow call
        assert "uses" not in each, name


def test_its_database_is_its_own_disposable_service(job: dict[str, Any]) -> None:
    ci_test_job = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))["jobs"]["test"]
    postgres = job["services"]["postgres"]

    assert set(job["services"]) == {"postgres"}
    assert postgres["image"] == ci_test_job["services"]["postgres"]["image"]
    assert "5432:5432" in postgres["ports"]
    assert job["env"]["DATABASE_URL"] == "postgresql+asyncpg://aegis:aegis@localhost:5432/aegis"
    for flag in ("AEGIS_REQUIRE_SERVICES", "RUN_EMBEDDING_INTEGRATION", "RUN_RAG_E2E_LIVE"):
        assert str(job["env"][flag]) == "1", flag


def test_no_step_can_point_the_tests_at_another_database(workflow: dict[Any, Any]) -> None:
    assert database_redirections(workflow) == []


def test_nothing_can_turn_a_failed_or_skipped_run_into_a_pass(workflow: dict[Any, Any]) -> None:
    assert failure_neutralizers(workflow) == []


def test_it_migrates_then_runs_exactly_the_live_test_file(job: dict[str, Any]) -> None:
    runs = [str(step.get("run", "")) for step in job["steps"]]
    migrate = runs.index("cd backend && uv run alembic upgrade head")
    pytest_step = _pytest_step(job)

    assert migrate < job["steps"].index(pytest_step)
    assert pytest_step["id"] == PYTEST_STEP_ID
    assert shlex.split(pytest_step["run"]) == EXPECTED_PYTEST_ARGV
    assert all("${{" not in run for run in runs)  # no expression is ever expanded into a shell


def test_the_check_runs_after_a_failed_pytest_step_and_expects_every_live_test(
    job: dict[str, Any],
) -> None:
    check = _check_step(job)

    assert job["steps"][-1] is check
    assert check["if"] == CHECK_STEP_IF
    assert check["env"]["PYTEST_OUTCOME"] == f"${{{{ steps.{PYTEST_STEP_ID}.outcome }}}}"
    assert int(check["env"]["EXPECTED_TESTS"]) == _live_test_count() > 0


def test_the_live_tests_are_gated_on_all_three_opt_ins() -> None:
    # Ordinary CI and local runs must never call the provider by accident.
    import tests.integration.test_rag_end_to_end_live as live

    marks = [decorator.mark for decorator in live.pytestmark]
    reasons = " ".join(str(m.kwargs.get("reason", "")) for m in marks if m.name == "skipif")

    assert {"llm_integration", "embedding_integration"} <= {m.name for m in marks}
    for gate in ("RUN_RAG_E2E_LIVE", "RUN_EMBEDDING_INTEGRATION", "GROQ_API_KEY"):
        assert f"{gate} is not set" in reasons, gate


def test_the_no_secrets_workflow_and_ordinary_ci_stay_secret_free_and_never_run_it() -> None:
    for name in ("rag-integration.yml", "ci.yml"):
        other = (WORKFLOWS / name).read_text(encoding="utf-8")

        assert secret_or_token_expressions(other) == [], name
        assert "environment:" not in other, name
        assert "test_rag_end_to_end_live" not in other, name
        assert "RUN_RAG_E2E_LIVE" not in other, name


# -- behaviour: the job's own "every live test ran" check, on hand-made JUnit reports ------------


def _check_script(job: dict[str, Any]) -> str:
    run = _check_step(job)["run"]
    match = re.search(r"python3 - <<'PY'\n(.*?)\nPY\s*$", run, flags=re.DOTALL)
    assert match, "no embedded python found"
    return match.group(1)


def _junit(*, tests: int, skipped: int = 0, failures: int = 0, errors: int = 0) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="{errors}" failures="{failures}" skipped="{skipped}" '
        f'tests="{tests}" time="1.0"></testsuite></testsuites>'
    )


def _run_check(
    job: dict[str, Any], tmp_path: Path, report: str | None, outcome: str = "success"
) -> subprocess.CompletedProcess[str]:
    if report is not None:
        (tmp_path / "rag-e2e-live-junit.xml").write_text(report, encoding="utf-8")
    step_env = {
        key: str(value)
        for key, value in _check_step(job)["env"].items()
        if key != "PYTEST_OUTCOME"  # an Actions expression; the runner fills it in
    }
    return subprocess.run(
        [sys.executable, "-I", "-c", _check_script(job)],
        cwd=tmp_path,
        env={
            **os.environ,
            **step_env,
            "PYTEST_OUTCOME": outcome,
            "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary.md"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_check_passes_when_every_live_test_ran_and_passed(
    job: dict[str, Any], tmp_path: Path
) -> None:
    result = _run_check(job, tmp_path, _junit(tests=_live_test_count()))

    assert result.returncode == 0, result.stderr
    summary = (tmp_path / "step-summary.md").read_text(encoding="utf-8")
    assert f"tests={_live_test_count()} skipped=0" in summary


@pytest.mark.parametrize(
    ("report", "outcome", "message"),
    [
        (_junit(tests=2, skipped=2), "success", "is the GROQ_API_KEY environment secret set?"),
        (_junit(tests=2, skipped=1), "success", "were skipped"),
        (_junit(tests=1), "success", "Expected exactly 2"),
        (_junit(tests=2, failures=1), "failure", "did not succeed"),
        (_junit(tests=2), "failure", "did not succeed"),
        (_junit(tests=2, errors=1), "success", "failed or errored"),
        ("<testsuites><broken", "failure", "No readable JUnit report"),
        (None, "skipped", "No readable JUnit report"),
    ],
    ids=[
        "no-key-so-all-skipped",
        "one-skipped",
        "too-few-tests",
        "a-failure",
        "pytest-failed-report-clean",
        "report-error-outcome-success",
        "unreadable-report",
        "pytest-never-ran",
    ],
)
def test_the_check_fails_unless_every_live_test_ran_and_passed(
    job: dict[str, Any], tmp_path: Path, report: str | None, outcome: str, message: str
) -> None:
    result = _run_check(job, tmp_path, report, outcome)

    assert result.returncode != 0
    assert message in result.stderr
    assert "## RAG end-to-end (live LLM)" in (tmp_path / "step-summary.md").read_text("utf-8")
