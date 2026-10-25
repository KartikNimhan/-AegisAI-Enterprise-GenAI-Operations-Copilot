"""Offline checks for the manual RAG integration workflow (`.github/workflows/rag-integration.yml`).

Structure: started by hand only, a read-only token that is not left in the checkout, no secret or
token reference in any expression, a GitHub-hosted runner with a timeout and one run at a time,
the same pinned actions as `ci.yml`, a database that is the job's own disposable service and
cannot be redirected by a step, nothing that turns a failure into a pass, and exactly the four
tests with exactly the expected pytest arguments. Each detector is also run on hand-made
positive and negative examples, so a check that silently matched nothing would fail here.

Behaviour: the job's "all four tests ran" check is EXTRACTED from the YAML and executed here on
hand-made JUnit reports, so a skipped, missing, short or failed run is proven to fail the job and
to still write its summary.

None of this runs the workflow or the four database-backed tests; the first manual run does that.
Static checks cannot see through deliberate obfuscation (for example a shell variable assembled
to spell `GITHUB_ENV`); they guard against ordinary edits and mistakes, not a hostile author.
"""

from __future__ import annotations

import copy
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOWS / "rag-integration.yml"
EVALUATION_CONFTEST = ROOT / "backend" / "tests" / "evaluation" / "conftest.py"
JOB = "embeddings-and-rag"
PYTEST_STEP_ID = "tests"
CHECK_STEP_NAME = "Fail unless all four tests ran and passed"
# Run after a failed pytest step (to write the summary, then fail), but not after a cancellation.
CHECK_STEP_IF = "${{ !cancelled() }}"
USES = re.compile(r"^\s*(?:- )?uses:\s*([\w.-]+/[\w./-]+)@(\S+)(.*)$", re.MULTILINE)
FOUR_TESTS = [
    "backend/tests/integration/test_embedding_model_live.py",
    "backend/tests/integration/test_rag_pipeline_live.py",
    "backend/tests/evaluation/test_recall_at_k.py",
    "backend/tests/evaluation/test_evaluate_runner.py",
]
EXPECTED_PYTEST_ARGV = [
    *("uv", "run", "pytest", "-v", "-rs", "-p", "no:cacheprovider"),
    "--junitxml=rag-integration-junit.xml",
    *FOUR_TESTS,
]

# -- detectors (each also tested on hand-made examples below) ----------------------------------

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
SECRETS_CONTEXT = re.compile(r"\bsecrets\b")
GITHUB_TOKEN_CONTEXT = re.compile(r"\bgithub\s*(?:\.\s*token\b|\[\s*['\"]token['\"]\s*\])")
STEP_ENV_FORBIDDEN = {"DATABASE_URL", "REDIS_URL"}
ENVIRONMENT_FILE_WRITES = re.compile(r"GITHUB_ENV|GITHUB_PATH|::set-env|::add-path")


def secret_or_token_expressions(text: str) -> list[str]:
    """Every `${{ ... }}` expression that reads the `secrets` context (any form: `secrets.X`,
    `secrets['X']`, `toJSON(secrets)`) or the job token (`github.token`, `github['token']`)."""
    return [
        expression.strip()
        for expression in EXPRESSION.findall(text)
        if SECRETS_CONTEXT.search(expression) or GITHUB_TOKEN_CONTEXT.search(expression)
    ]


def database_redirections(workflow: dict[Any, Any]) -> list[str]:
    """Places that could point a step at a different database or Redis: a workflow- or step-level
    `env` entry, or a write to the runner's environment/path files from a script."""
    found = [f"workflow env {key}" for key in STEP_ENV_FORBIDDEN & set(workflow.get("env") or {})]
    for job_name, job in workflow["jobs"].items():
        for index, step in enumerate(job.get("steps", [])):
            label = f"{job_name} step {index} ({step.get('name') or step.get('uses') or 'run'})"
            for key in STEP_ENV_FORBIDDEN & set(step.get("env") or {}):
                found.append(f"{label}: env {key}")
            if ENVIRONMENT_FILE_WRITES.search(str(step.get("run", ""))):
                found.append(f"{label}: writes the runner environment or path")
    return found


def failure_neutralizers(workflow: dict[Any, Any]) -> list[str]:
    """Anything that could let a failed or skipped run pass: `continue-on-error` on the job or any
    step, an `if:` on the job or on any step but the final check, or a different `if:` there."""
    found: list[str] = []
    for job_name, job in workflow["jobs"].items():
        for key in ("continue-on-error", "if"):
            if key in job:
                found.append(f"job {job_name}: {key}")
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


# -- fixtures and helpers ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def raw() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(raw: str) -> dict[Any, Any]:
    return yaml.safe_load(raw)


@pytest.fixture(scope="module")
def job(workflow: dict[Any, Any]) -> dict[str, Any]:
    return workflow["jobs"][JOB]


def _step(job: dict[str, Any], fragment: str) -> dict[str, Any]:
    matches = [
        s for s in job["steps"] if fragment in str(s.get("name", "")) + str(s.get("run", ""))
    ]
    assert len(matches) == 1, f"expected one step matching {fragment!r}, found {len(matches)}"
    return matches[0]


def _runs_pytest(step: dict[str, Any]) -> bool:
    return "uv run pytest" in str(step.get("run", ""))


def _pytest_step(job: dict[str, Any]) -> dict[str, Any]:
    steps = [s for s in job["steps"] if _runs_pytest(s)]
    assert len(steps) == 1, f"expected exactly one pytest step, found {len(steps)}"
    return steps[0]


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


def test_no_expression_reads_a_secret_or_the_job_token(workflow: dict[Any, Any], raw: str) -> None:
    assert secret_or_token_expressions(raw) == []
    assert "GITHUB_TOKEN" not in raw
    for name, job in workflow["jobs"].items():
        assert "secrets" not in job, name  # e.g. `secrets: inherit` on a reusable-workflow call
        assert "uses" not in job, name  # no reusable workflow (it could receive secrets)
        assert "environment" not in job, name


def test_it_is_one_job_on_a_github_hosted_runner_with_a_timeout(
    workflow: dict[Any, Any], job: dict[str, Any]
) -> None:
    assert set(workflow["jobs"]) == {JOB}
    assert str(job["runs-on"]).startswith("ubuntu-")
    assert "self-hosted" not in str(job["runs-on"])
    assert 0 < int(job["timeout-minutes"]) <= 60
    assert workflow["concurrency"]["group"].startswith("rag-integration-")


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


def test_its_database_is_its_own_disposable_service(job: dict[str, Any]) -> None:
    ci_test_job = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))["jobs"]["test"]
    postgres = job["services"]["postgres"]

    assert set(job["services"]) == {"postgres"}
    assert postgres["image"] == ci_test_job["services"]["postgres"]["image"]
    assert "5432:5432" in postgres["ports"]
    assert job["env"]["DATABASE_URL"] == "postgresql+asyncpg://aegis:aegis@localhost:5432/aegis"
    assert str(job["env"]["AEGIS_REQUIRE_SERVICES"]) == "1"
    assert str(job["env"]["RUN_EMBEDDING_INTEGRATION"]) == "1"


def test_no_step_can_point_the_tests_at_another_database(workflow: dict[Any, Any]) -> None:
    assert database_redirections(workflow) == []


def test_nothing_can_turn_a_failed_or_skipped_run_into_a_pass(workflow: dict[Any, Any]) -> None:
    assert failure_neutralizers(workflow) == []


def test_it_migrates_then_runs_exactly_the_four_tests_with_exact_arguments(
    job: dict[str, Any],
) -> None:
    runs = [str(step.get("run", "")) for step in job["steps"]]
    migrate = runs.index("cd backend && uv run alembic upgrade head")
    pytest_step = _pytest_step(job)

    assert migrate < job["steps"].index(pytest_step)
    assert pytest_step["id"] == PYTEST_STEP_ID
    # Exact: no extra path or directory, no `-k`/`-m` filter, no `--showlocals`, no lost `-rs`.
    assert shlex.split(pytest_step["run"]) == EXPECTED_PYTEST_ARGV
    assert all("${{" not in run for run in runs)  # no expression is ever expanded into a shell


def test_the_check_runs_after_a_failed_pytest_step_and_knows_its_outcome(
    job: dict[str, Any],
) -> None:
    check = _step(job, CHECK_STEP_NAME)

    assert job["steps"][-1] is check
    assert check["if"] == CHECK_STEP_IF
    assert check["env"]["PYTEST_OUTCOME"] == f"${{{{ steps.{PYTEST_STEP_ID}.outcome }}}}"
    assert str(check["env"]["EXPECTED_TESTS"]) == str(len(FOUR_TESTS))


def test_the_evaluation_fixture_fails_instead_of_skipping_when_services_are_required() -> None:
    # Two of the four tests use this fixture. A bare `pytest.skip` here once turned an unreachable
    # database into a silent skip even with AEGIS_REQUIRE_SERVICES=1.
    source = EVALUATION_CONFTEST.read_text(encoding="utf-8")

    assert not re.search(r"\bpytest\.skip\(", source)
    assert "service_unavailable(" in source


# -- the detectors themselves, on hand-made examples -------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "X: ${{ secrets.X }}",
        "X: ${{ secrets['X'] }}",
        "X: ${{ toJSON(secrets) }}",
        "X: ${{ format('{0}', secrets.X) }}",
        "X: ${{ github.token }}",
        "X: ${{ github['token'] }}",
        "X: ${{\n  secrets.X\n}}",
    ],
)
def test_the_secret_detector_finds_every_form(snippet: str) -> None:
    assert secret_or_token_expressions(snippet) != []


@pytest.mark.parametrize(
    "snippet",
    [
        "group: rag-${{ github.ref }}",
        "version: ${{ env.UV_VERSION }}",
        "X: ${{ steps.tests.outcome }}",
        "# this workflow uses no secrets",
    ],
)
def test_the_secret_detector_ignores_harmless_text(snippet: str) -> None:
    assert secret_or_token_expressions(snippet) == []


def _mutated(workflow: dict[Any, Any], change: Any) -> dict[Any, Any]:
    copied = copy.deepcopy(workflow)
    change(copied["jobs"][JOB])
    return copied


def _pytest_of(job: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in job["steps"] if _runs_pytest(s))


def _check_of(job: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in job["steps"] if s.get("name") == CHECK_STEP_NAME)


@pytest.mark.parametrize(
    "change",
    [
        lambda j: _pytest_of(j).setdefault("env", {}).update(DATABASE_URL="postgresql://x/y"),
        lambda j: _pytest_of(j).setdefault("env", {}).update(REDIS_URL="redis://x:6379/0"),
        lambda j: j["steps"].insert(1, {"run": 'echo "DATABASE_URL=x" >> "$GITHUB_ENV"'}),
        lambda j: j["steps"].insert(1, {"run": 'echo "/opt/bin" >> "${GITHUB_PATH}"'}),
    ],
    ids=["step-env-database", "step-env-redis", "github-env-write", "github-path-write"],
)
def test_the_redirection_detector_finds_overrides(workflow: dict[Any, Any], change: Any) -> None:
    assert database_redirections(_mutated(workflow, change)) != []


@pytest.mark.parametrize(
    "change",
    [
        lambda j: j.update({"continue-on-error": True}),
        lambda j: j.update({"if": "false"}),
        lambda j: _pytest_of(j).update({"continue-on-error": True}),
        lambda j: _pytest_of(j).update({"if": "${{ false }}"}),
        lambda j: _check_of(j).update({"continue-on-error": True}),
        lambda j: _check_of(j).update({"if": "false"}),
        lambda j: _check_of(j).pop("if"),
        lambda j: j["steps"][0].update({"if": "false"}),
    ],
    ids=[
        "job-continue-on-error",
        "job-if",
        "pytest-continue-on-error",
        "pytest-if-false",
        "check-continue-on-error",
        "check-if-false",
        "check-if-removed",
        "setup-step-if",
    ],
)
def test_the_neutralizer_detector_finds_every_bypass(workflow: dict[Any, Any], change: Any) -> None:
    assert failure_neutralizers(_mutated(workflow, change)) != []


# -- behaviour: the job's own "all four ran" check, on hand-made JUnit reports -------------------


def _check_script(job: dict[str, Any]) -> str:
    run = _step(job, CHECK_STEP_NAME)["run"]
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
    report_path = tmp_path / "rag-integration-junit.xml"
    if report is not None:
        report_path.write_text(report, encoding="utf-8")
    summary = tmp_path / "step-summary.md"
    step_env = {
        key: str(value)
        for key, value in _step(job, CHECK_STEP_NAME)["env"].items()
        if key != "PYTEST_OUTCOME"  # an Actions expression; the runner fills it in
    }
    return subprocess.run(
        [sys.executable, "-I", "-c", _check_script(job)],
        cwd=tmp_path,
        env={
            **os.environ,
            **step_env,
            "PYTEST_OUTCOME": outcome,
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_check_passes_when_all_four_tests_ran_and_passed(
    job: dict[str, Any], tmp_path: Path
) -> None:
    result = _run_check(job, tmp_path, _junit(tests=4))

    assert result.returncode == 0, result.stderr
    assert "tests=4 skipped=0" in (tmp_path / "step-summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("report", "outcome", "message"),
    [
        (_junit(tests=4, skipped=4), "success", "were skipped"),  # pytest itself exits 0 for this
        (_junit(tests=4, skipped=1), "success", "were skipped"),
        (_junit(tests=3), "success", "Expected exactly 4"),
        (_junit(tests=0), "success", "Expected exactly 4"),
        (_junit(tests=4, failures=1), "failure", "did not succeed"),
        (_junit(tests=4, errors=1), "failure", "did not succeed"),
        (_junit(tests=4), "failure", "did not succeed"),  # e.g. a crash after the report
        (_junit(tests=4, failures=1), "success", "failed or errored"),
        ("<testsuites><broken", "failure", "No readable JUnit report"),
        (None, "failure", "No readable JUnit report"),
        (None, "skipped", "No readable JUnit report"),  # an earlier setup step failed
    ],
    ids=[
        "all-skipped",
        "one-skipped",
        "too-few-tests",
        "no-tests",
        "a-failure",
        "an-error",
        "pytest-failed-report-clean",
        "report-failure-outcome-success",
        "unreadable-report",
        "no-report",
        "pytest-never-ran",
    ],
)
def test_the_check_fails_unless_all_four_ran_and_passed(
    job: dict[str, Any], tmp_path: Path, report: str | None, outcome: str, message: str
) -> None:
    result = _run_check(job, tmp_path, report, outcome)

    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize(
    ("report", "outcome"),
    [(_junit(tests=4, failures=2), "failure"), (None, "failure")],
    ids=["after-test-failures", "after-no-report"],
)
def test_a_failed_run_still_writes_its_summary(
    job: dict[str, Any], tmp_path: Path, report: str | None, outcome: str
) -> None:
    result = _run_check(job, tmp_path, report, outcome)

    assert result.returncode != 0
    summary = (tmp_path / "step-summary.md").read_text(encoding="utf-8")
    assert "## RAG integration" in summary
    assert f"pytest step outcome: {outcome}" in summary
