"""Offline structural checks for the security-scanning configuration.

These tests read `.github/workflows/security.yml`, `.github/dependabot.yml`, `.gitleaks.toml` and
the docs, and check how they are written: least privilege, pinned actions, reporting-only
behaviour, narrow allowlists, and report/artifact steps. They do NOT run any scanner and prove
nothing about whether the scanners work or what they would find; the first workflow run does that.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "security.yml"
DEPENDABOT_PATH = ROOT / ".github" / "dependabot.yml"
GITLEAKS_PATH = ROOT / ".gitleaks.toml"

JOBS = {"python-audit", "npm-audit", "secret-scan", "image-scan"}


@pytest.fixture(scope="module")
def raw() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(raw: str) -> dict[str, Any]:
    return yaml.safe_load(raw)


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job["steps"]


# -- structure and triggers ----------------------------------------------------------------


def test_the_four_scan_jobs_exist_and_are_separate_from_ci(workflow: dict[str, Any]) -> None:
    assert set(workflow["jobs"]) == JOBS
    assert WORKFLOW_PATH.name != "ci.yml"


def test_it_runs_on_prs_pushes_a_weekly_schedule_and_manually(workflow: dict[str, Any]) -> None:
    keyed: dict[Any, Any] = workflow  # PyYAML (YAML 1.1) reads the key `on` as the boolean True
    triggers = keyed[True] if True in keyed else keyed["on"]

    assert {"pull_request", "push", "schedule", "workflow_dispatch"} <= set(triggers)
    assert len(triggers["schedule"]) == 1 and triggers["schedule"][0]["cron"].split()[4] == "1"


# -- permissions ----------------------------------------------------------------------------


def test_default_permissions_are_read_only(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_only_the_image_job_may_write_security_events(workflow: dict[str, Any]) -> None:
    for name, job in workflow["jobs"].items():
        permissions = job.get("permissions")
        if name == "image-scan":
            assert permissions == {"contents": "read", "security-events": "write"}
        else:
            assert permissions is None, f"{name} must inherit the read-only default"


def test_no_job_uses_repository_secrets_or_a_pull_request_target_trigger(raw: str) -> None:
    assert "secrets." not in raw
    assert "pull_request_target" not in raw


# -- pinning ---------------------------------------------------------------------------------


def test_every_third_party_action_is_pinned_to_a_full_sha_with_a_version_comment(raw: str) -> None:
    uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)(.*)$", raw, flags=re.MULTILINE)

    assert len(uses) >= 10
    for reference, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", reference), (
            f"not SHA-pinned: {reference}"
        )
        assert re.search(r"#\s*v?\d+\.\d+(\.\d+)?", rest), f"no version comment on {reference}"


def test_tool_versions_and_the_gitleaks_checksum_are_pinned(workflow: dict[str, Any]) -> None:
    env = workflow["env"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", env["PIP_AUDIT_VERSION"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", env["GITLEAKS_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["GITLEAKS_SHA256"])


def test_gitleaks_is_verified_before_it_is_extracted(workflow: dict[str, Any]) -> None:
    script = next(
        s["run"]
        for s in _steps(workflow["jobs"]["secret-scan"])
        if "Download gitleaks" in s.get("name", "")
    )

    assert script.index("sha256sum -c") < script.index("tar -xzf")


# -- reporting only --------------------------------------------------------------------------


def test_every_job_is_non_blocking(workflow: dict[str, Any]) -> None:
    for name, job in workflow["jobs"].items():
        assert job["continue-on-error"] is True, name


def test_scan_commands_cannot_fail_the_step(workflow: dict[str, Any]) -> None:
    scans = {
        "python-audit": "pip-audit",
        "npm-audit": "npm audit",
        "secret-scan": "gitleaks git",
    }
    for job_name, marker in scans.items():
        commands = [
            line
            for step in _steps(workflow["jobs"][job_name])
            if "GITHUB_STEP_SUMMARY" not in str(step.get("run", ""))  # summaries only read reports
            for line in str(step.get("run", "")).splitlines()
            if marker in line and not line.lstrip().startswith("#")
        ]
        assert commands, f"no scan command found in {job_name}"
        for command in commands:
            assert "|| " in command, f"scan command can fail the step: {command}"


def test_no_blocking_exit_code_or_severity_gate_is_configured(
    raw: str, workflow: dict[str, Any]
) -> None:
    assert "--audit-level" not in raw
    assert "--fail-on" not in raw
    assert re.search(r"--exit-code\s+0\b", raw)
    for step in _steps(workflow["jobs"]["image-scan"]):
        if str(step.get("uses", "")).startswith("aquasecurity/trivy-action"):
            assert step["with"]["exit-code"] == "0"


# -- redaction -------------------------------------------------------------------------------


def test_gitleaks_redacts_and_scans_the_full_history(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["secret-scan"]
    checkout = next(s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/checkout"))
    scan = next(s["run"] for s in _steps(job) if "gitleaks git" in str(s.get("run", "")))

    assert checkout["with"]["fetch-depth"] == 0
    assert "--redact" in scan
    assert "--config .gitleaks.toml" in scan


def test_the_secret_summary_never_prints_the_matched_text(workflow: dict[str, Any]) -> None:
    summary = next(
        s["run"]
        for s in _steps(workflow["jobs"]["secret-scan"])
        if "Summarise" in s.get("name", "")
    )

    # Field names that could carry the matched text (the heading may say "Secret scan").
    for forbidden in ('"Match"', '"Secret"', "message", "snippet", "contextRegion"):
        assert forbidden not in summary


# -- reports and fallbacks -------------------------------------------------------------------


@pytest.mark.parametrize("job_name", sorted(JOBS))
def test_every_job_keeps_an_artifact_and_writes_a_summary_even_after_failure(
    workflow: dict[str, Any], job_name: str
) -> None:
    steps = _steps(workflow["jobs"][job_name])
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    summaries = [s for s in steps if "GITHUB_STEP_SUMMARY" in str(s.get("run", ""))]

    assert uploads and all(s.get("if") == "always()" for s in uploads)
    assert summaries and all(s.get("if") == "always()" for s in summaries)


def test_summaries_say_when_a_report_is_missing_instead_of_looking_clean(raw: str) -> None:
    assert raw.count("this is NOT a clean result") >= 4


def test_sarif_upload_to_code_scanning_is_optional_with_the_artifact_as_fallback(
    workflow: dict[str, Any],
) -> None:
    steps = _steps(workflow["jobs"]["image-scan"])
    uploads = [
        s for s in steps if str(s.get("uses", "")).startswith("github/codeql-action/upload-sarif")
    ]

    assert len(uploads) == 3
    for step in uploads:
        assert step["continue-on-error"] is True
        assert "hashFiles(" in step["if"]
    assert any(
        str(s.get("uses", "")).startswith("actions/upload-artifact")
        and "trivy" in s["with"]["path"]
        for s in steps
    )


def test_the_image_job_builds_but_never_pushes(workflow: dict[str, Any]) -> None:
    builds = [
        s
        for s in _steps(workflow["jobs"]["image-scan"])
        if str(s.get("uses", "")).startswith("docker/build-push-action")
    ]

    assert len(builds) == 3
    for step in builds:
        assert step["with"]["push"] is False and step["with"]["load"] is True


def test_the_existing_ci_workflow_was_not_turned_into_a_scanner() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for tool in ("gitleaks", "trivy", "pip-audit", "npm audit"):
        assert tool not in ci


# -- gitleaks configuration -----------------------------------------------------------------


@pytest.fixture(scope="module")
def gitleaks() -> dict[str, Any]:
    return tomllib.loads(GITLEAKS_PATH.read_text(encoding="utf-8"))


def test_default_rules_stay_on(gitleaks: dict[str, Any]) -> None:
    assert gitleaks["extend"]["useDefault"] is True


def test_the_allowlist_is_exactly_the_three_confirmed_template_files(
    gitleaks: dict[str, Any],
) -> None:
    allowed = {pattern for entry in gitleaks["allowlists"] for pattern in entry["paths"]}

    assert allowed == {
        r"^\.env\.example$",
        r"^infra/kubernetes/backend-secret\.example\.yaml$",
        r"^infra/kubernetes/postgres-secret\.example\.yaml$",
    }


def test_every_allowlist_entry_is_justified_anchored_and_points_at_a_real_file(
    gitleaks: dict[str, Any],
) -> None:
    for entry in gitleaks["allowlists"]:
        assert len(entry["description"]) > 40
        assert set(entry) <= {
            "description",
            "paths",
        }  # no regexes over content, no commits, no rules
        for pattern in entry["paths"]:
            assert pattern.startswith("^") and pattern.endswith("$")
            assert ".*" not in pattern and "tests" not in pattern and "|" not in pattern
            path = pattern[1:-1].replace("\\.", ".")
            assert (ROOT / path).is_file(), f"allowlisted file does not exist: {path}"


def test_no_source_test_or_dev_idp_path_is_allowlisted(gitleaks: dict[str, Any]) -> None:
    text = GITLEAKS_PATH.read_text(encoding="utf-8")

    for broad in ("backend/", "tests", "frontend/", "keycloak", "docker-compose"):
        assert broad not in text.split("[[allowlists]]", 1)[1], broad


# -- dependabot ------------------------------------------------------------------------------


def test_dependabot_covers_the_four_ecosystems_weekly() -> None:
    config = yaml.safe_load(DEPENDABOT_PATH.read_text(encoding="utf-8"))
    updates = config["updates"]

    assert config["version"] == 2
    assert {u["package-ecosystem"] for u in updates} == {"uv", "npm", "github-actions", "docker"}
    assert all(u["schedule"]["interval"] == "weekly" for u in updates)


def test_dependabot_directories_contain_what_they_update() -> None:
    updates = yaml.safe_load(DEPENDABOT_PATH.read_text(encoding="utf-8"))["updates"]
    by_ecosystem: dict[str, set[str]] = {}
    for update in updates:
        by_ecosystem.setdefault(update["package-ecosystem"], set()).add(update["directory"])

    assert by_ecosystem["uv"] == {"/"} and (ROOT / "uv.lock").is_file()
    assert by_ecosystem["npm"] == {"/frontend/web"}
    assert (ROOT / "frontend" / "web" / "package-lock.json").is_file()
    assert by_ecosystem["github-actions"] == {"/"}
    dockerfiles = {
        "/" + str(p.parent.relative_to(ROOT)).replace("\\", "/") if p.parent != ROOT else "/"
        for p in ROOT.glob("**/Dockerfile")
        if "node_modules" not in p.parts and ".venv" not in p.parts
    }
    assert by_ecosystem["docker"] == dockerfiles


# -- documentation ---------------------------------------------------------------------------


def test_the_docs_say_the_baseline_has_not_been_scanned() -> None:
    doc = (ROOT / "docs" / "operations" / "security-scanning.md").read_text(encoding="utf-8")

    assert "never run" in doc and "no baseline" in doc.lower()
    assert "reporting-only" in doc.lower()
    assert "NOT a clean result" in doc


def test_security_policy_exists_and_invents_no_contact_address() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Reporting a vulnerability" in policy
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", policy)
