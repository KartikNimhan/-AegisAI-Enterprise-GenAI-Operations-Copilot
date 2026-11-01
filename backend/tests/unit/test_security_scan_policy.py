"""The blocking policy for the security scans (AIGSEC-007), run against hand-made reports.

No scanner runs here: the reports have the shapes the real tools write (and the workflow's own
summary tests use), so this proves the decisions: what blocks, what is only reported, what counts
as a failed scan, and how exceptions behave.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "security_scan_policy", ROOT / "scripts" / "security_scan_policy.py"
)
policy = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["security_scan_policy"] = policy  # dataclasses look their module up
_spec.loader.exec_module(policy)  # type: ignore[union-attr]

TODAY = dt.date(2026, 11, 1)
PASS, FINDINGS, FAILED = policy.PASS, policy.FINDINGS, policy.FAILED


def _write(directory: Path, name: str, content: Any) -> None:
    text = content if isinstance(content, str) else json.dumps(content)
    (directory / name).write_text(text, encoding="utf-8")


def _exceptions(directory: Path, *entries: dict[str, str]) -> Path:
    path = directory / "exceptions.json"
    _write(directory, "exceptions.json", {"exceptions": list(entries)})
    return path


def _run(scanner: str, directory: Path, exceptions: Path | None = None) -> tuple[int, str]:
    out = io.StringIO()
    code = policy.run(scanner, directory, exceptions or directory / "none.json", TODAY, out)
    return code, out.getvalue()


def _exception(ident: str, scanner: str, *, expires: str = "2026-12-01") -> dict[str, str]:
    return {
        "id": ident,
        "scanner": scanner,
        "reason": "not reachable in this app",
        "expires": expires,
    }


# -- pip-audit ------------------------------------------------------------------------------


def _pip(directory: Path, vulns: list[dict[str, Any]], *, code: str = "1") -> None:
    for name in ("runtime", "all-groups"):
        _write(directory, f"requirements-{name}.status", "ok:120")
        _write(directory, f"pip-audit-{name}.exit", code)
        deps = [{"name": "safe", "version": "1.0", "vulns": []}]
        if vulns:
            deps.append({"name": "lib", "version": "1.0", "vulns": vulns})
        _write(directory, f"pip-audit-{name}.json", {"dependencies": deps})


def test_pip_a_clean_audit_passes(tmp_path: Path) -> None:
    _pip(tmp_path, [], code="0")

    assert _run("pip-audit", tmp_path)[0] == PASS


def test_pip_a_fixable_vulnerability_blocks(tmp_path: Path) -> None:
    _pip(tmp_path, [{"id": "PYSEC-1", "fix_versions": ["1.1"], "aliases": ["CVE-1"]}])

    code, output = _run("pip-audit", tmp_path)

    assert code == FINDINGS
    assert "blocking: runtime: lib 1.0: PYSEC-1 (fix available)" in output


def test_pip_a_vulnerability_without_a_fix_is_reported_not_blocking(tmp_path: Path) -> None:
    _pip(tmp_path, [{"id": "PYSEC-2", "fix_versions": []}])

    code, output = _run("pip-audit", tmp_path)

    assert code == PASS
    assert "no fix released yet" in output


def test_pip_an_exception_by_alias_applies(tmp_path: Path) -> None:
    _pip(tmp_path, [{"id": "PYSEC-1", "fix_versions": ["1.1"], "aliases": ["CVE-1"]}])

    code, output = _run(
        "pip-audit", tmp_path, _exceptions(tmp_path, _exception("CVE-1", "pip-audit"))
    )

    assert code == PASS
    assert "(excepted)" in output


@pytest.mark.parametrize("broken", ["status", "exit", "report", "inconsistent"])
def test_pip_an_incomplete_audit_is_a_failure_never_a_pass(tmp_path: Path, broken: str) -> None:
    _pip(tmp_path, [], code="0")
    if broken == "status":
        _write(tmp_path, "requirements-runtime.status", "export-failed")
    elif broken == "exit":
        _write(tmp_path, "pip-audit-runtime.exit", "2")
    elif broken == "report":
        _write(tmp_path, "pip-audit-runtime.json", "not json")
    else:
        _write(tmp_path, "pip-audit-runtime.exit", "1")  # says "findings" but lists none

    assert _run("pip-audit", tmp_path)[0] == FAILED


# -- npm audit ------------------------------------------------------------------------------


def _npm(directory: Path, vias: list[Any], *, code: str = "1") -> None:
    for name in ("runtime", "all"):
        _write(directory, f"npm-audit-{name}.exit", code)
        report = {
            "vulnerabilities": {"pkg": {"severity": "high", "via": vias}} if vias else {},
            "metadata": {
                "vulnerabilities": {"total": len(vias)},
                "dependencies": {"total": 200},
            },
        }
        _write(directory, f"npm-audit-{name}.json", report)


def _via(severity: str, ghsa: str = "GHSA-aaaa-bbbb-cccc") -> dict[str, str]:
    return {"severity": severity, "url": f"https://github.com/advisories/{ghsa}"}


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_npm_high_and_critical_block(tmp_path: Path, severity: str) -> None:
    _npm(tmp_path, [_via(severity)])

    code, output = _run("npm-audit", tmp_path)

    assert code == FINDINGS
    assert "GHSA-aaaa-bbbb-cccc" in output


@pytest.mark.parametrize("severity", ["moderate", "low", "info"])
def test_npm_lower_severities_are_reported_not_blocking(tmp_path: Path, severity: str) -> None:
    _npm(tmp_path, [_via(severity)])

    assert _run("npm-audit", tmp_path)[0] == PASS


def test_npm_transitive_references_alone_do_not_count_twice(tmp_path: Path) -> None:
    _npm(tmp_path, ["other-package"])

    assert _run("npm-audit", tmp_path)[0] == PASS


def test_npm_an_exception_covers_exactly_that_advisory(tmp_path: Path) -> None:
    _npm(tmp_path, [_via("high"), _via("critical", "GHSA-xxxx-yyyy-zzzz")])
    exceptions = _exceptions(tmp_path, _exception("GHSA-aaaa-bbbb-cccc", "npm-audit"))

    code, output = _run("npm-audit", tmp_path, exceptions)

    assert code == FINDINGS  # the other advisory still blocks
    assert "GHSA-xxxx-yyyy-zzzz" in output


def test_npm_a_registry_error_is_a_failure(tmp_path: Path) -> None:
    _npm(tmp_path, [])
    _write(tmp_path, "npm-audit-runtime.json", {"error": {"code": "ENOTFOUND"}})

    assert _run("npm-audit", tmp_path)[0] == FAILED


# -- gitleaks ----------------------------------------------------------------------------------


def _gitleaks(directory: Path, results: list[Any], *, code: str = "0") -> None:
    _write(directory, "gitleaks.exit", code)
    _write(directory, "gitleaks.sarif", {"runs": [{"results": results}]})


_LEAK = {
    "ruleId": "generic-api-key",
    "message": {"text": "REDACTED"},
    "locations": [
        {"physicalLocation": {"artifactLocation": {"uri": "a.py"}, "region": {"startLine": 3}}}
    ],
}


def test_gitleaks_no_finding_passes(tmp_path: Path) -> None:
    _gitleaks(tmp_path, [])

    assert _run("gitleaks", tmp_path)[0] == PASS


def test_gitleaks_any_potential_secret_blocks_and_only_its_location_is_printed(
    tmp_path: Path,
) -> None:
    _gitleaks(tmp_path, [{**_LEAK, "Secret": "sk-not-real-but-must-not-print"}])

    code, output = _run("gitleaks", tmp_path)

    assert code == FINDINGS
    assert "generic-api-key at a.py:3" in output
    assert "sk-not-real" not in output


def test_gitleaks_a_failed_scan_is_a_failure_even_with_an_empty_report(tmp_path: Path) -> None:
    _gitleaks(tmp_path, [], code="1")

    assert _run("gitleaks", tmp_path)[0] == FAILED


# -- Trivy -------------------------------------------------------------------------------------


def _trivy(
    directory: Path, results: list[Any], monkeypatch: pytest.MonkeyPatch, **outcomes: str
) -> None:
    for image, build_var, scan_var in policy.TRIVY_IMAGES:
        monkeypatch.setenv(build_var, outcomes.get(build_var, "success"))
        monkeypatch.setenv(scan_var, outcomes.get(scan_var, "success"))
        _write(directory, f"trivy-{image}.sarif", {"runs": [{"results": results}]})


@pytest.mark.parametrize(
    ("level", "expected"), [("error", FINDINGS), ("warning", PASS), ("note", PASS)]
)
def test_trivy_blocks_on_critical_and_high_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str, expected: int
) -> None:
    _trivy(tmp_path, [{"ruleId": "CVE-2026-1", "level": level}], monkeypatch)

    assert _run("trivy", tmp_path)[0] == expected


def test_trivy_a_failed_build_or_scan_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trivy(tmp_path, [], monkeypatch, BUILD_FRONTEND="failure")

    code, output = _run("trivy", tmp_path)

    assert code == FAILED
    assert "frontend: the image was not built" in output


def test_trivy_an_exception_applies_to_that_cve_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trivy(tmp_path, [{"ruleId": "CVE-2026-1", "level": "error"}], monkeypatch)

    assert (
        _run("trivy", tmp_path, _exceptions(tmp_path, _exception("CVE-2026-1", "trivy")))[0] == PASS
    )
    assert (
        _run("trivy", tmp_path, _exceptions(tmp_path, _exception("CVE-2026-1", "npm-audit")))[0]
        == FINDINGS
    )


# -- the exceptions file -----------------------------------------------------------------------


def test_an_expired_exception_no_longer_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trivy(tmp_path, [{"ruleId": "CVE-2026-1", "level": "error"}], monkeypatch)
    expired = _exceptions(tmp_path, _exception("CVE-2026-1", "trivy", expires="2026-10-31"))

    code, output = _run("trivy", tmp_path, expired)

    assert code == FINDINGS
    assert "expired on 2026-10-31" in output


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "CVE-1", "scanner": "trivy", "reason": "x", "expires": "2026-12-01"},  # no reason
        {"id": "*", "scanner": "trivy", "reason": "everything is fine", "expires": "2026-12-01"},
        {"id": "CVE-1", "scanner": "nessus", "reason": "unknown scanner", "expires": "2026-12-01"},
        {"id": "CVE-1", "scanner": "trivy", "reason": "too far ahead", "expires": "2028-01-01"},
        {"id": "CVE-1", "scanner": "trivy", "reason": "no expiry given"},
    ],
)
def test_a_broad_permanent_or_malformed_exception_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: dict[str, str]
) -> None:
    _trivy(tmp_path, [], monkeypatch)

    code, output = _run("trivy", tmp_path, _exceptions(tmp_path, entry))

    assert code == FAILED
    assert "exceptions file is invalid" in output


def test_the_committed_exceptions_file_is_valid_and_empty() -> None:
    path = ROOT / ".github" / "security-scan-exceptions.json"

    for scanner in policy.SCANNERS:
        excepted, notes = policy.load_exceptions(path, scanner, TODAY)
        assert excepted == set() and notes == []
