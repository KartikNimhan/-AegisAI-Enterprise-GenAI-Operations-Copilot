"""Offline checks for the security-scanning configuration.

Two kinds of test:

* Structure: `.github/workflows/security.yml`, `.github/dependabot.yml`, `.gitleaks.toml` and the
  docs are read and checked for least privilege, pinned actions, reporting-only behaviour, narrow
  allowlists and report steps.
* Behaviour: the workflow's own shell steps and summary scripts are EXTRACTED from the YAML and
  executed here, with stand-in `uv`/`uvx`/`npm`/`gitleaks` programs and hand-made report files, to
  prove how failures are reported: a failed or incomplete scan, a missing or empty report, skipped
  packages and real findings must each be told apart, and none may look like a clean result.

None of this runs a real scanner or says anything about what the scanners would find; the first
workflow run does that.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
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


def _step(workflow: dict[str, Any], job: str, fragment: str) -> dict[str, Any]:
    matches = [s for s in _steps(workflow["jobs"][job]) if fragment in s.get("name", "")]
    assert len(matches) == 1, f"expected exactly one step matching {fragment!r} in {job}"
    return matches[0]


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


def test_every_third_party_action_is_pinned_to_a_full_sha_with_a_version_comment(
    raw: str,
) -> None:
    uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)(.*)$", raw, flags=re.MULTILINE)

    assert len(uses) >= 10
    for reference, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", reference), reference
        assert re.search(r"#\s*v?\d+\.\d+(\.\d+)?", rest), f"no version comment on {reference}"


def test_tool_versions_and_the_gitleaks_checksum_are_pinned(workflow: dict[str, Any]) -> None:
    env = workflow["env"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", env["PIP_AUDIT_VERSION"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", env["GITLEAKS_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["GITLEAKS_SHA256"])
    assert int(env["MIN_PACKAGES"]) >= 10


def test_gitleaks_is_verified_before_it_is_extracted(workflow: dict[str, Any]) -> None:
    script = _step(workflow, "secret-scan", "Download gitleaks")["run"]

    assert script.index("sha256sum -c") < script.index("tar -xzf")


def _trivy_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for s in _steps(workflow["jobs"]["image-scan"])
        if str(s.get("uses", "")).startswith("aquasecurity/trivy-action")
    ]


def test_the_trivy_binary_is_pinned_explicitly_above_every_reviewed_advisory(
    workflow: dict[str, Any],
) -> None:
    version = workflow["env"]["TRIVY_VERSION"]
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    assert match, version
    numbers = tuple(int(part) for part in match.groups())

    # Advisories reviewed (see the comment in the workflow): fixed in 0.71.0, 0.71.1 and 0.72.0.
    assert numbers >= (0, 72, 0)
    # 0.69.4, 0.69.5 and 0.69.6 were published by an attacker (CVE-2026-33634).
    assert numbers not in {(0, 69, 4), (0, 69, 5), (0, 69, 6)}
    steps = _trivy_steps(workflow)
    assert len(steps) == 3
    for step in steps:
        assert step["with"]["version"] == "${{ env.TRIVY_VERSION }}"


def test_the_trivy_action_is_not_a_release_hit_by_the_march_2026_compromise(raw: str) -> None:
    pattern = r"aquasecurity/trivy-action@[0-9a-f]{40}\s*#\s*v?(\d+)\.(\d+)\.(\d+)"
    versions = re.findall(pattern, raw)

    assert versions
    # GHSA-69fq-xp46-6x23: every release before 0.35.0 was replaced with malicious code.
    assert all(tuple(map(int, v)) >= (0, 35, 0) for v in versions)


# -- reporting only --------------------------------------------------------------------------


def test_every_job_is_non_blocking(workflow: dict[str, Any]) -> None:
    for name, job in workflow["jobs"].items():
        assert job["continue-on-error"] is True, name


def test_scan_commands_cannot_fail_their_step(workflow: dict[str, Any]) -> None:
    scans = {
        "python-audit": "uvx --from",
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
    for step in _trivy_steps(workflow):
        assert step["with"]["exit-code"] == "0"


# -- failures must stay visible ----------------------------------------------------------------


def test_scanner_exit_statuses_are_saved_not_discarded(workflow: dict[str, Any]) -> None:
    assert 'echo "$code" > gitleaks.exit' in _step(workflow, "secret-scan", "Scan history")["run"]
    assert 'echo "$code" > "npm-audit-' in _step(workflow, "npm-audit", "Audit")["run"]
    assert 'echo "$code" > "pip-audit-' in _step(workflow, "python-audit", "Export")["run"]


def test_the_export_step_runs_under_pipefail_in_an_explicit_bash(workflow: dict[str, Any]) -> None:
    step = _step(workflow, "python-audit", "Export")

    assert step["shell"] == "bash"  # GitHub adds `-o pipefail` only for an explicit `shell: bash`
    assert "set -o pipefail" in step["run"]


def test_summary_steps_always_run_and_never_swallow_their_own_crash(
    workflow: dict[str, Any],
) -> None:
    for job in JOBS:
        summaries = [s for s in _steps(workflow["jobs"][job]) if "Summarise" in s.get("name", "")]
        assert len(summaries) == 1, job
        assert summaries[0]["if"] == "always()"
        assert "|| true" not in summaries[0]["run"]


def test_trivy_builds_and_scans_are_independent_and_their_outcomes_reach_the_summary(
    workflow: dict[str, Any],
) -> None:
    steps = _steps(workflow["jobs"]["image-scan"])
    builds = [s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action")]
    scans = _trivy_steps(workflow)
    summary_env = _step(workflow, "image-scan", "Summarise")["env"]

    assert len(builds) == 3 and len(scans) == 3
    for step in builds + scans:
        assert step["continue-on-error"] is True and step["id"]
    for scan in scans:
        assert scan["if"] == "always()"  # an earlier failure must not skip the remaining scans
    for step in builds + scans:
        assert f"steps.{step['id']}.outcome" in "".join(summary_env.values())


def test_sarif_is_only_offered_for_a_scan_that_succeeded(workflow: dict[str, Any]) -> None:
    uploads = [
        s
        for s in _steps(workflow["jobs"]["image-scan"])
        if str(s.get("uses", "")).startswith("github/codeql-action/upload-sarif")
    ]

    assert len(uploads) == 3
    for step in uploads:
        assert step["continue-on-error"] is True
        assert "hashFiles(" in step["if"] and ".outcome == 'success'" in step["if"]


# -- redaction -------------------------------------------------------------------------------


def test_gitleaks_redacts_and_scans_the_full_history(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["secret-scan"]
    checkout = next(s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/checkout"))
    scan = _step(workflow, "secret-scan", "Scan history")["run"]

    assert checkout["with"]["fetch-depth"] == 0
    assert "--redact" in scan
    assert "--config .gitleaks.toml" in scan


def test_the_secret_summary_never_reads_the_matched_text(workflow: dict[str, Any]) -> None:
    summary = _step(workflow, "secret-scan", "Summarise")["run"]

    # Field names that could carry the matched text (the heading may say "Secret scan").
    for forbidden in ('"Match"', '"Secret"', "message", "snippet", "contextRegion"):
        assert forbidden not in summary


# -- reports and fallbacks -------------------------------------------------------------------


@pytest.mark.parametrize("job_name", sorted(JOBS))
def test_every_job_keeps_an_artifact_after_failure(workflow: dict[str, Any], job_name: str) -> None:
    steps = _steps(workflow["jobs"][job_name])
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    summaries = [s for s in steps if "GITHUB_STEP_SUMMARY" in str(s.get("run", ""))]

    assert uploads and all(s.get("if") == "always()" for s in uploads)
    assert summaries and all(s.get("if") == "always()" for s in summaries)


def test_exit_status_files_are_kept_with_the_reports(workflow: dict[str, Any]) -> None:
    for job, needle in (
        ("python-audit", ".exit"),
        ("npm-audit", ".exit"),
        ("secret-scan", "gitleaks.exit"),
    ):
        upload = next(
            s
            for s in _steps(workflow["jobs"][job])
            if str(s.get("uses", "")).startswith("actions/upload-artifact")
        )
        assert needle in upload["with"]["path"]


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


# ==========================================================================================
# Behaviour: the workflow's own summary scripts, executed on hand-made inputs
# ==========================================================================================

NOT_CLEAN = "NOT a clean result"


def _embedded_python(run: str) -> str:
    match = re.search(r"python3 - <<'PY'\n(.*?)\nPY\s*$", run, flags=re.DOTALL)
    assert match, "no embedded python found"
    return match.group(1)


class Summary:
    def __init__(self, text: str, stdout: str) -> None:
        self.text = text
        self.stdout = stdout  # workflow commands such as ::warning


def _run_summary(
    workflow: dict[str, Any],
    job: str,
    tmp_path: Path,
    files: dict[str, str],
    env: dict[str, str] | None = None,
) -> Summary:
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    summary_file = tmp_path / "step-summary.md"
    summary_file.unlink(missing_ok=True)
    code = _embedded_python(_step(workflow, job, "Summarise")["run"])
    base_env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary_file), "MIN_PACKAGES": "20"}
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        env={**base_env, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr  # a summary must never crash
    text = summary_file.read_text(encoding="utf-8") if summary_file.exists() else ""
    return Summary(text, completed.stdout)


def _pip_files(
    name: str, *, status: str, exit_code: str | None, deps: Any = None
) -> dict[str, str]:
    files = {f"requirements-{name}.status": status}
    if exit_code is not None:
        files[f"pip-audit-{name}.exit"] = exit_code
    if deps is not None:
        files[f"pip-audit-{name}.json"] = json.dumps({"dependencies": deps, "fixes": []})
    return files


CLEAN_DEP = {"name": "fastapi", "version": "0.115.0", "vulns": []}
VULNERABLE_DEP = {
    "name": "pillow",
    "version": "9.0.0",
    "vulns": [{"id": "PYSEC-2099-1", "fix_versions": ["9.0.1"], "aliases": [], "description": "x"}],
}
SKIPPED_DEP = {
    "name": "torch",
    "skip_reason": "Dependency not found on PyPI and could not be audited",
}


def _both_sets(**kwargs: Any) -> dict[str, str]:
    return {**_pip_files("runtime", **kwargs), **_pip_files("all-groups", **kwargs)}


def test_pip_a_complete_clean_audit_is_reported_as_clean(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = _both_sets(status="ok:120", exit_code="0", deps=[CLEAN_DEP])

    result = _run_summary(workflow, "python-audit", tmp_path, files)

    assert result.text.count("audit complete, no known vulnerabilities") == 2
    assert NOT_CLEAN not in result.text and "::warning" not in result.stdout


def test_pip_findings_are_reported_with_ids_and_fixes(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = _both_sets(status="ok:120", exit_code="1", deps=[CLEAN_DEP, VULNERABLE_DEP])

    result = _run_summary(workflow, "python-audit", tmp_path, files)

    assert "findings reported" in result.text
    assert "PYSEC-2099-1" in result.text and "9.0.1" in result.text
    assert "1 with known vulnerabilities" in result.text


def test_pip_a_skipped_entry_without_a_version_does_not_truncate_the_summary(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    deps = [SKIPPED_DEP, VULNERABLE_DEP, CLEAN_DEP]  # pip-audit gives skipped entries no `version`
    files = _both_sets(status="ok:120", exit_code="1", deps=deps)

    result = _run_summary(workflow, "python-audit", tmp_path, files)

    assert "skipped `torch`" in result.text and "could not be audited" in result.text
    assert "PYSEC-2099-1" in result.text  # listed AFTER the skipped entry
    assert result.text.count("1 skipped (NOT audited)") == 2  # and the second set was reached
    assert result.text.index("`all-groups`") > result.text.index("`runtime`")


def test_pip_skipped_packages_alone_are_never_called_a_clean_result(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = _both_sets(status="ok:120", exit_code="0", deps=[CLEAN_DEP, SKIPPED_DEP])

    result = _run_summary(workflow, "python-audit", tmp_path, files)

    assert "NOT audited" in result.text and NOT_CLEAN in result.text
    assert "audit complete, no known vulnerabilities" not in result.text


def test_pip_malformed_entries_are_counted_and_do_not_stop_the_remaining_ones(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    deps = [None, "oops", 7, {"name": "no-vulns-key"}, VULNERABLE_DEP, CLEAN_DEP]
    files = _both_sets(status="ok:120", exit_code="1", deps=deps)

    result = _run_summary(workflow, "python-audit", tmp_path, files)

    assert "4 unreadable entries" in result.text
    assert "PYSEC-2099-1" in result.text and "`all-groups`" in result.text


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"status": "export-failed", "exit_code": None}, "could not be exported"),
        ({"status": "too-few:3", "exit_code": None}, "Only 3 pinned packages"),
        ({"status": "too-few:0", "exit_code": None}, "Only 0 pinned packages"),
        ({"status": "ok:120", "exit_code": None}, "did not run"),
        ({"status": "ok:120", "exit_code": "2", "deps": [CLEAN_DEP]}, "exit status 2"),
        ({"status": "ok:120", "exit_code": "0", "deps": []}, "lists 0 packages"),
        ({"status": "ok:120", "exit_code": "0"}, "no readable report"),
        ({"status": "ok:120", "exit_code": "1", "deps": [CLEAN_DEP]}, "lists no vulnerability"),
    ],
)
def test_pip_invalid_audits_are_reported_as_such_and_never_as_clean(
    workflow: dict[str, Any], tmp_path: Path, kwargs: dict[str, Any], reason: str
) -> None:
    result = _run_summary(workflow, "python-audit", tmp_path, _both_sets(**kwargs))

    assert result.text.count("INVALID AUDIT") == 2
    assert reason in result.text
    assert NOT_CLEAN in result.text
    assert "audit complete" not in result.text
    assert result.stdout.count("::warning") == 2  # surfaced as run annotations too


def test_pip_nothing_at_all_is_an_invalid_audit_not_a_crash(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    result = _run_summary(workflow, "python-audit", tmp_path, {})

    assert result.text.count("INVALID AUDIT") == 2


# -- npm summary -------------------------------------------------------------------------------


def _npm_report(counts: dict[str, int] | None = None, *, packages: int = 160) -> str:
    levels = {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 0, **(counts or {})}
    levels["total"] = sum(levels.values())
    metadata = {"vulnerabilities": levels, "dependencies": {"total": packages}}
    return json.dumps({"auditReportVersion": 2, "metadata": metadata})


def _npm_files(exit_code: str | None, report: str | None) -> dict[str, str]:
    files: dict[str, str] = {}
    for name in ("runtime", "all"):
        if exit_code is not None:
            files[f"npm-audit-{name}.exit"] = exit_code
        if report is not None:
            files[f"npm-audit-{name}.json"] = report
    return files


def test_npm_clean_and_findings_are_distinguished(workflow: dict[str, Any], tmp_path: Path) -> None:
    clean = _run_summary(workflow, "npm-audit", tmp_path, _npm_files("0", _npm_report()))
    assert clean.text.count("audit complete, no known vulnerabilities") == 2
    assert NOT_CLEAN not in clean.text

    found = _run_summary(workflow, "npm-audit", tmp_path, _npm_files("1", _npm_report({"high": 2})))
    assert "findings reported" in found.text and "high: 2" in found.text


@pytest.mark.parametrize(
    ("exit_code", "report", "reason"),
    [
        (None, _npm_report(), "did not run"),
        ("1", json.dumps({"error": {"code": "ENOTFOUND", "summary": "x"}}), "reported an error"),
        ("1", "not json", "no readable report"),
        ("0", json.dumps({"metadata": {}}), "no vulnerability counts"),
        ("0", _npm_report(packages=0), "covers 0 packages"),
        ("1", _npm_report(), "reported no vulnerability"),
    ],
)
def test_npm_invalid_audits_are_never_reported_as_clean(
    workflow: dict[str, Any], tmp_path: Path, exit_code: str | None, report: str, reason: str
) -> None:
    result = _run_summary(workflow, "npm-audit", tmp_path, _npm_files(exit_code, report))

    assert result.text.count("INVALID AUDIT") == 2 and reason in result.text
    assert NOT_CLEAN in result.text and "audit complete" not in result.text


# -- gitleaks summary --------------------------------------------------------------------------

EMPTY_SARIF = json.dumps(
    {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "gitleaks"}}, "results": []}]}
)


def _sarif_with_finding() -> str:
    result = {
        "ruleId": "generic-api-key",
        "message": {"text": "generic-api-key has detected a secret. SENTINEL-MESSAGE"},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "app/x.py"},
                    "region": {"startLine": 12, "snippet": {"text": "SENTINEL-SNIPPET"}},
                }
            }
        ],
        "partialFingerprints": {
            "commitSha": "0123456789abcdef",
            "email": "dev@example.test",
            "commitMessage": "SENTINEL-COMMIT-MESSAGE",
        },
    }
    return json.dumps({"runs": [{"results": [result]}]})


def test_gitleaks_a_complete_scan_with_no_findings_is_not_flagged_as_a_failure(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = {"gitleaks.exit": "0", "gitleaks.sarif": EMPTY_SARIF}

    result = _run_summary(workflow, "secret-scan", tmp_path, files)

    assert "Scan complete: no potential secrets" in result.text
    assert "not proof that none exist" in result.text
    assert NOT_CLEAN not in result.text


def test_gitleaks_an_empty_report_after_a_failed_scan_is_not_proof_of_a_clean_scan(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = {"gitleaks.exit": "1", "gitleaks.sarif": EMPTY_SARIF}

    result = _run_summary(workflow, "secret-scan", tmp_path, files)

    assert "FAILED or the scan is INCOMPLETE (exit status 1)" in result.text
    assert NOT_CLEAN in result.text and "Scan complete" not in result.text
    assert "::warning" in result.stdout


def test_gitleaks_partial_findings_are_labelled_partial(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = {"gitleaks.exit": "1", "gitleaks.sarif": _sarif_with_finding()}

    result = _run_summary(workflow, "secret-scan", tmp_path, files)

    assert "INCOMPLETE" in result.text and "Partial findings so far: 1" in result.text


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"gitleaks.sarif": EMPTY_SARIF}, "did not run"),
        ({"gitleaks.exit": "0"}, "no valid report"),
        ({"gitleaks.exit": "0", "gitleaks.sarif": "{not json"}, "no valid report"),
        ({"gitleaks.exit": "0", "gitleaks.sarif": json.dumps({"runs": []})}, "no valid report"),
        ({"gitleaks.exit": "0", "gitleaks.sarif": json.dumps({"runs": [{}]})}, "no valid report"),
        ({}, "did not run"),
    ],
)
def test_gitleaks_missing_or_invalid_evidence_is_never_reported_as_clean(
    workflow: dict[str, Any], tmp_path: Path, files: dict[str, str], reason: str
) -> None:
    result = _run_summary(workflow, "secret-scan", tmp_path, files)

    assert reason in result.text and NOT_CLEAN in result.text
    assert "Scan complete" not in result.text


def test_gitleaks_findings_show_where_but_never_what(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = {"gitleaks.exit": "0", "gitleaks.sarif": _sarif_with_finding()}

    result = _run_summary(workflow, "secret-scan", tmp_path, files)

    assert "1 potential secret(s)" in result.text and "Findings reported" in result.text
    assert "`generic-api-key` in `app/x.py:12` (commit `0123456789`)" in result.text
    for leaked in ("SENTINEL", "dev@example.test"):
        assert leaked not in result.text and leaked not in result.stdout


def test_gitleaks_one_unreadable_finding_does_not_hide_the_others(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    good = json.loads(_sarif_with_finding())["runs"][0]["results"][0]
    sarif = json.dumps({"runs": [{"results": [{"ruleId": "broken"}, good]}]})

    result = _run_summary(
        workflow, "secret-scan", tmp_path, {"gitleaks.exit": "0", "gitleaks.sarif": sarif}
    )

    assert "one finding could not be read" in result.text and "app/x.py:12" in result.text


# -- trivy summary -----------------------------------------------------------------------------

ALL_OK = {
    f"{kind}_{name}".upper(): "success"
    for kind in ("build", "scan")
    for name in ("backend", "frontend", "streamlit")
}


def _trivy_sarif(levels: list[str]) -> str:
    results = [{"ruleId": f"CVE-{i}", "level": level} for i, level in enumerate(levels)]
    return json.dumps({"runs": [{"results": results}]})


def test_trivy_clean_findings_and_failures_are_three_different_messages(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = {
        "trivy-backend.sarif": _trivy_sarif([]),
        "trivy-frontend.sarif": _trivy_sarif(["error", "error", "warning"]),
    }  # streamlit: the scan step "succeeded" but left no report

    result = _run_summary(workflow, "image-scan", tmp_path, files, ALL_OK)

    assert "`backend`: scan complete, no fixable vulnerabilities" in result.text
    assert "`frontend`: scan complete, **3 finding(s)** (error: 2, warning: 1" in result.text
    assert "`streamlit`: **The scan step succeeded but left no valid report" in result.text
    assert result.text.count(NOT_CLEAN) == 1


def test_trivy_one_failed_scan_is_reported_and_does_not_hide_the_others(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    names = ("backend", "frontend", "streamlit")
    files = {f"trivy-{n}.sarif": _trivy_sarif(["note"]) for n in names}
    env = {**ALL_OK, "SCAN_BACKEND": "failure"}  # a partial report exists but the step failed

    result = _run_summary(workflow, "image-scan", tmp_path, files, env)

    assert "`backend`: **The Trivy scan step did not succeed (outcome: failure)" in result.text
    assert "`frontend`: scan complete" in result.text
    assert "`streamlit`: scan complete" in result.text


def test_trivy_a_failed_build_means_not_scanned_and_a_skipped_step_is_not_success(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    names = ("backend", "frontend", "streamlit")
    files = {f"trivy-{n}.sarif": _trivy_sarif([]) for n in names}
    env = {**ALL_OK, "BUILD_FRONTEND": "failure", "SCAN_STREAMLIT": "skipped"}

    result = _run_summary(workflow, "image-scan", tmp_path, files, env)

    assert "image build did not succeed (outcome: failure)" in result.text
    assert "scan step did not succeed (outcome: skipped)" in result.text
    assert result.text.count(NOT_CLEAN) == 2


def test_trivy_missing_outcomes_and_garbage_reports_do_not_crash_or_look_clean(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    files = {
        "trivy-backend.sarif": "{broken",
        "trivy-frontend.sarif": json.dumps({"runs": [{"results": "x"}]}),
    }

    result = _run_summary(workflow, "image-scan", tmp_path, files, {**ALL_OK, "SCAN_STREAMLIT": ""})

    assert result.text.count(NOT_CLEAN) == 3 and "scan complete" not in result.text


# ==========================================================================================
# Behaviour: the workflow's own shell steps, executed with stand-in tools
# ==========================================================================================


def _find_bash() -> str | None:
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if Path(candidate).exists():
                return candidate
        return None  # `bash` on PATH may be WSL's, which cannot see these Windows paths
    return shutil.which("bash")


BASH = _find_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="a POSIX bash is not available here")

SHIM_UV = """#!/usr/bin/env bash
case "${SHIM_UV:-ok}" in
  fail) echo "uv: export failed" >&2; exit 3 ;;
  empty) exit 0 ;;
  few) for i in 1 2 3; do echo "pkg$i==1.0.$i"; done ;;
  *) echo "--index-url https://example.invalid/simple"
     for i in $(seq 1 "${SHIM_COUNT:-130}"); do
       echo "pkg$i==1.0.$i ; python_version >= '3.12'"
     done ;;
esac
"""

SHIM_UVX = """#!/usr/bin/env bash
echo "uvx $*" >> "$SHIM_LOG"
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; fi
  shift
done
if [ -n "${SHIM_AUDIT_JSON:-}" ] && [ -n "$out" ]; then echo "$SHIM_AUDIT_JSON" > "$out"; fi
exit "${SHIM_AUDIT_EXIT:-0}"
"""

SHIM_NPM = """#!/usr/bin/env bash
echo "npm $*" >> "$SHIM_LOG"
[ -n "${SHIM_NPM_JSON:-}" ] && echo "$SHIM_NPM_JSON"
exit "${SHIM_NPM_EXIT:-0}"
"""

SHIM_GITLEAKS = """#!/usr/bin/env bash
echo "gitleaks $*" >> "$SHIM_LOG"
report=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--report-path" ]; then report="$2"; fi
  shift
done
if [ -n "${SHIM_SARIF:-}" ] && [ -n "$report" ]; then echo "$SHIM_SARIF" > "$report"; fi
exit "${SHIM_GITLEAKS_EXIT:-0}"
"""


def _install(directory: Path, programs: dict[str, str]) -> None:
    directory.mkdir(exist_ok=True)
    for name, body in programs.items():
        (directory / name).write_text(body, encoding="utf-8", newline="\n")
        (directory / name).chmod(0o755)


def _run_shell_step(
    workflow: dict[str, Any],
    job: str,
    fragment: str,
    tmp_path: Path,
    shims: dict[str, str],
    env: dict[str, str],
    local: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Runs a step's `run` script the way the runner does (`-e`, plus `-o pipefail` only for an
    explicit `shell: bash`), with `shims` on PATH and `local` programs in the working directory."""
    assert BASH is not None
    step = _step(workflow, job, fragment)
    bin_dir = tmp_path / "bin"
    _install(bin_dir, shims)
    _install(tmp_path, local or {})
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8", newline="\n")
    shell_flags = ["-eo", "pipefail"] if step.get("shell") == "bash" else ["-e"]
    full_env = {
        **os.environ,
        **workflow["env"],
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "SHIM_LOG": str(tmp_path / "calls.log"),
        **env,
    }
    return subprocess.run(
        [BASH, "--noprofile", "--norc", *shell_flags, str(script)],
        cwd=tmp_path,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _read(tmp_path: Path, name: str) -> str:
    return (tmp_path / name).read_text(encoding="utf-8").strip()


EXPORT_TOOLS = {"uv": SHIM_UV, "uvx": SHIM_UVX}


@needs_bash
def test_export_step_audits_both_sets_and_keeps_each_exit_status(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    env = {"SHIM_AUDIT_JSON": json.dumps({"dependencies": [CLEAN_DEP]}), "SHIM_AUDIT_EXIT": "1"}

    done = _run_shell_step(workflow, "python-audit", "Export", tmp_path, EXPORT_TOOLS, env)

    assert done.returncode == 0, done.stderr  # reporting only: the step never fails
    for name in ("runtime", "all-groups"):
        assert _read(tmp_path, f"requirements-{name}.status") == "ok:130"
        assert _read(tmp_path, f"pip-audit-{name}.exit") == "1"
        requirements = (tmp_path / f"requirements-{name}.txt").read_text(encoding="utf-8")
        assert not requirements.startswith("-") and "--index-url" not in requirements
    calls = _calls(tmp_path)
    assert len(calls) == 2 and all("--no-deps" in c and "--disable-pip" in c for c in calls)
    assert all("pip-audit==2.10.1" in c for c in calls)


@needs_bash
def test_export_step_records_a_failed_export_and_audits_nothing(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    done = _run_shell_step(
        workflow, "python-audit", "Export", tmp_path, EXPORT_TOOLS, {"SHIM_UV": "fail"}
    )

    assert done.returncode == 0
    assert _read(tmp_path, "requirements-runtime.status") == "export-failed"
    assert _read(tmp_path, "requirements-all-groups.status") == "export-failed"
    assert _calls(tmp_path) == []  # pip-audit never ran on a missing export
    assert not (tmp_path / "pip-audit-runtime.exit").exists()


@needs_bash
@pytest.mark.parametrize(("mode", "expected"), [("empty", "too-few:0"), ("few", "too-few:3")])
def test_export_step_rejects_an_empty_or_tiny_export(
    workflow: dict[str, Any], tmp_path: Path, mode: str, expected: str
) -> None:
    done = _run_shell_step(
        workflow, "python-audit", "Export", tmp_path, EXPORT_TOOLS, {"SHIM_UV": mode}
    )

    assert done.returncode == 0
    assert _read(tmp_path, "requirements-runtime.status") == expected
    assert _calls(tmp_path) == []


@needs_bash
def test_export_step_saves_a_pip_audit_crash_status_without_failing(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    done = _run_shell_step(
        workflow, "python-audit", "Export", tmp_path, EXPORT_TOOLS, {"SHIM_AUDIT_EXIT": "2"}
    )

    assert done.returncode == 0
    assert _read(tmp_path, "pip-audit-runtime.exit") == "2"
    assert not (tmp_path / "pip-audit-runtime.json").exists()


@needs_bash
def test_a_failed_export_flows_through_to_an_invalid_audit_summary(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    _run_shell_step(workflow, "python-audit", "Export", tmp_path, EXPORT_TOOLS, {"SHIM_UV": "fail"})

    result = _run_summary(workflow, "python-audit", tmp_path, {})

    assert result.text.count("INVALID AUDIT") == 2 and "audit complete" not in result.text


@needs_bash
@pytest.mark.parametrize("exit_status", ["0", "1"])
def test_gitleaks_status_survives_into_the_summary(
    workflow: dict[str, Any], tmp_path: Path, exit_status: str
) -> None:
    env = {"SHIM_GITLEAKS_EXIT": exit_status, "SHIM_SARIF": EMPTY_SARIF}

    done = _run_shell_step(
        workflow,
        "secret-scan",
        "Scan history",
        tmp_path,
        {},
        env,
        local={"gitleaks": SHIM_GITLEAKS},
    )

    assert done.returncode == 0, done.stderr  # the step itself never fails
    assert _read(tmp_path, "gitleaks.exit") == exit_status
    call = _calls(tmp_path)[0]
    for argument in (
        "--redact",
        "--exit-code 0",
        "--report-format sarif",
        "--config .gitleaks.toml",
    ):
        assert argument in call
    summary = _run_summary(workflow, "secret-scan", tmp_path, {})
    if exit_status == "0":
        assert "Scan complete" in summary.text and NOT_CLEAN not in summary.text
    else:
        assert "INCOMPLETE" in summary.text and NOT_CLEAN in summary.text


@needs_bash
def test_npm_step_saves_each_exit_status_for_both_passes(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    env = {"SHIM_NPM_JSON": _npm_report({"high": 1}), "SHIM_NPM_EXIT": "1"}

    done = _run_shell_step(workflow, "npm-audit", "Audit", tmp_path, {"npm": SHIM_NPM}, env)

    assert done.returncode == 0
    assert _read(tmp_path, "npm-audit-runtime.exit") == "1"
    assert _read(tmp_path, "npm-audit-all.exit") == "1"
    calls = _calls(tmp_path)
    assert any("--omit=dev" in c for c in calls) and any("--omit=dev" not in c for c in calls)


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
        assert set(entry) <= {"description", "paths"}  # no content regexes, commits or rules
        for pattern in entry["paths"]:
            assert pattern.startswith("^") and pattern.endswith("$")
            assert ".*" not in pattern and "tests" not in pattern and "|" not in pattern
            path = pattern[1:-1].replace("\\.", ".")
            assert (ROOT / path).is_file(), f"allowlisted file does not exist: {path}"


def test_no_source_test_or_dev_idp_path_is_allowlisted() -> None:
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


def _doc() -> str:
    return (ROOT / "docs" / "operations" / "security-scanning.md").read_text(encoding="utf-8")


def _baseline_log_rows() -> list[str]:
    log = _doc().split("## Baseline log", 1)[1].split("\n## ", 1)[0]
    rows = [line.strip() for line in log.splitlines() if line.startswith("|")]
    return rows[2:]  # after the header row and the separator


def test_the_docs_never_present_a_partly_reviewed_baseline_as_clean() -> None:
    # Some reports were downloaded and reviewed; CI's Gitleaks reports and the later runs were not
    # (the artifacts need a signed-in account). The doc must say so and not imply a clean result.
    doc = " ".join(_doc().split())  # compare across line wraps

    assert "have not been reviewed" in doc and "no reviewed baseline" in doc.lower()
    assert "does not claim the repository is free of vulnerabilities or secrets" in doc
    assert "reporting-only" in doc.lower()
    assert "NOT a clean result" in doc
    assert "Not reviewed yet: CI's `gitleaks-report`" in doc


def test_every_baseline_log_entry_says_when_and_where_it_came_from() -> None:
    rows = _baseline_log_rows()

    assert rows, "the baseline log has no entries"
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 4, row
        date, scan, result, decision = cells
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date), row
        # A CI run with its commit, a local scan, or reports that came before a named fix.
        assert re.search(r"run #\d+ \(`[0-9a-f]{7}`\)|\*\*locally\*\*|before the fixes", scan), row
        assert result and decision, row
        if "before the fixes" in scan:
            assert re.search(r"`[0-9a-f]{7}`", decision), row  # the fix, named by its commit


def test_the_docs_explain_how_each_outcome_is_told_apart() -> None:
    doc = _doc()

    for phrase in ("INVALID AUDIT", "INCOMPLETE", "skipped", "Findings reported", "exit status"):
        assert phrase in doc, phrase
    assert "v0.74.0" in doc and "CVE-2026-33634" in doc


def test_security_policy_exists_and_invents_no_contact_address() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Reporting a vulnerability" in policy
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", policy)
