"""The blocking policy for the security scans (AIGSEC-007), run as the last step of each job in
.github/workflows/security.yml after the reporting summary.

Three outcomes, three exit codes, so a failing job always says why:

  0  PASS      the scan completed and nothing blocking was found
  1  FINDINGS  the scan completed and found something the policy blocks on
  2  FAILED    the scanner did not complete, or its report is missing, unreadable or inconsistent:
               never treated as a pass

What blocks (docs/operations/security-scanning.md, "Blocking policy"):

  pip-audit  any known vulnerability that has a released fix. pip-audit reports carry no
             severity, so every fixable advisory is treated as blocking (stricter than
             High/Critical). Advisories with no fix yet are reported, not blocking.
  npm audit  advisories rated high or critical. Moderate and low are reported, not blocking.
  gitleaks   any potential secret. A false positive is excluded in .gitleaks.toml, in review.
  Trivy      results at SARIF level "error", which Trivy uses for CRITICAL and HIGH. Medium and
             low are reported, not blocking. Unfixed vulnerabilities are not scanned for.

Exceptions live in .github/security-scan-exceptions.json. Each names one advisory id (CVE, GHSA,
PYSEC, ...) for one scanner, with a reason and an expiry date at most 180 days ahead; an expired
exception stops applying, and a malformed file fails the run. There is no wildcard.

Only identifiers, package names and counts are printed, never a matched secret.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASS, FINDINGS, FAILED = 0, 1, 2
SCANNERS = ("pip-audit", "npm-audit", "gitleaks", "trivy")
MAX_EXCEPTION_DAYS = 180
DEFAULT_EXCEPTIONS = (
    Path(__file__).resolve().parents[1] / ".github" / "security-scan-exceptions.json"
)
TRIVY_IMAGES = (
    ("backend", "BUILD_BACKEND", "SCAN_BACKEND"),
    ("frontend", "BUILD_FRONTEND", "SCAN_FRONTEND"),
    ("streamlit", "BUILD_STREAMLIT", "SCAN_STREAMLIT"),
)


class InvalidExceptionsError(Exception):
    pass


@dataclass
class Verdict:
    blocking: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def code(self) -> int:
        if self.failures:
            return FAILED
        return FINDINGS if self.blocking else PASS


def load_exceptions(path: Path, scanner: str, today: dt.date) -> tuple[set[str], list[str]]:
    """The advisory ids excepted for `scanner` today, and notes about expired ones."""
    if not path.exists():
        return set(), []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["exceptions"]
        if not isinstance(entries, list):
            raise TypeError("exceptions is not a list")
    except Exception as exc:
        raise InvalidExceptionsError(f"{path.name} is unreadable ({type(exc).__name__})") from exc

    active: set[str] = set()
    notes: list[str] = []
    for index, entry in enumerate(entries):
        try:
            ident, owner, reason = entry["id"], entry["scanner"], entry["reason"]
            expires = dt.date.fromisoformat(entry["expires"])
        except Exception as exc:
            raise InvalidExceptionsError(
                f"exception #{index} is malformed ({type(exc).__name__})"
            ) from exc
        if not isinstance(ident, str) or not ident or "*" in ident:
            raise InvalidExceptionsError(f"exception #{index} must name exactly one advisory id")
        if owner not in SCANNERS:
            raise InvalidExceptionsError(f"exception #{index} names an unknown scanner {owner!r}")
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            raise InvalidExceptionsError(f"exception #{index} ({ident}) needs a reason")
        if (expires - today).days > MAX_EXCEPTION_DAYS:
            raise InvalidExceptionsError(
                f"exception #{index} ({ident}) expires more than {MAX_EXCEPTION_DAYS} days ahead"
            )
        if owner != scanner:
            continue
        if expires < today:
            notes.append(f"exception for {ident} expired on {expires}: it no longer applies")
            continue
        active.add(ident)
    return active, notes


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# -- pip-audit ----------------------------------------------------------------------------------


def check_pip_audit(directory: Path, excepted: set[str]) -> Verdict:
    verdict = Verdict()
    for name in ("runtime", "all-groups"):
        status = _read(directory / f"requirements-{name}.status")
        if status is None or not status.startswith("ok:"):
            verdict.failures.append(f"{name}: the locked requirements were not exported ({status})")
            continue
        code = _read(directory / f"pip-audit-{name}.exit")
        if code not in ("0", "1"):
            verdict.failures.append(f"{name}: pip-audit did not complete (exit status {code})")
            continue
        try:
            deps = _json(directory / f"pip-audit-{name}.json")["dependencies"]
            if not isinstance(deps, list) or not deps:
                raise ValueError("no dependencies")
        except Exception as exc:
            verdict.failures.append(f"{name}: no usable pip-audit report ({type(exc).__name__})")
            continue
        vulnerable = 0
        for entry in deps:
            if not isinstance(entry, dict):
                verdict.failures.append(f"{name}: an unreadable report entry")
                continue
            if entry.get("skip_reason"):
                verdict.notes.append(f"{name}: {entry.get('name', '?')} was not audited (skipped)")
                continue
            for vuln in entry.get("vulns") or []:
                vulnerable += 1
                ids = {str(vuln.get("id", "?")), *map(str, vuln.get("aliases") or [])}
                label = (
                    f"{entry.get('name', '?')} {entry.get('version', '?')}: {vuln.get('id', '?')}"
                )
                if ids & excepted:
                    verdict.notes.append(f"{name}: {label} (excepted)")
                elif vuln.get("fix_versions"):
                    verdict.blocking.append(f"{name}: {label} (fix available)")
                else:
                    verdict.notes.append(f"{name}: {label} (no fix released yet)")
        if code == "1" and vulnerable == 0:
            verdict.failures.append(f"{name}: pip-audit exited 1 but reported no vulnerability")
    return verdict


# -- npm audit ----------------------------------------------------------------------------------


def _advisory_id(via: dict[str, Any]) -> str:
    url = str(via.get("url") or "")
    return url.rstrip("/").rsplit("/", 1)[-1] if url else str(via.get("source", "?"))


def check_npm_audit(directory: Path, excepted: set[str]) -> Verdict:
    verdict = Verdict()
    for name in ("runtime", "all"):
        code = _read(directory / f"npm-audit-{name}.exit")
        if code is None:
            verdict.failures.append(f"{name}: npm audit did not run")
            continue
        try:
            data = _json(directory / f"npm-audit-{name}.json")
            if not isinstance(data, dict) or "error" in data:
                raise ValueError("npm audit reported an error")
            vulnerabilities = data.get("vulnerabilities", {})
            counts = data["metadata"]["vulnerabilities"]
            total = int(counts.get("total", 0))
            if int(data["metadata"]["dependencies"]["total"]) <= 0:
                raise ValueError("0 packages")
        except Exception as exc:
            verdict.failures.append(f"{name}: no usable npm audit report ({type(exc).__name__})")
            continue
        if code != "0" and total == 0:
            verdict.failures.append(f"{name}: npm audit exited {code} but reported nothing")
            continue
        seen: set[str] = set()
        for package, entry in vulnerabilities.items():
            for via in entry.get("via", []) if isinstance(entry, dict) else []:
                if not isinstance(via, dict):
                    continue  # a transitive reference; the advisory itself is listed elsewhere
                advisory = _advisory_id(via)
                severity = str(via.get("severity", "")).lower()
                key = f"{advisory}:{package}"
                if key in seen:
                    continue
                seen.add(key)
                label = f"{name}: {package} {advisory} ({severity})"
                if severity not in ("high", "critical"):
                    verdict.notes.append(label)
                elif advisory in excepted:
                    verdict.notes.append(f"{label} (excepted)")
                else:
                    verdict.blocking.append(label)
    return verdict


# -- gitleaks -----------------------------------------------------------------------------------


def check_gitleaks(directory: Path, excepted: set[str]) -> Verdict:
    verdict = Verdict()
    code = _read(directory / "gitleaks.exit")
    if code != "0":
        verdict.failures.append(f"gitleaks did not complete (exit status {code})")
        return verdict
    try:
        runs = _json(directory / "gitleaks.sarif")["runs"]
        results = runs[0]["results"]
        if not isinstance(results, list):
            raise TypeError("results is not a list")
    except Exception as exc:
        verdict.failures.append(f"gitleaks produced no valid report ({type(exc).__name__})")
        return verdict
    for result in results:
        try:
            location = result["locations"][0]["physicalLocation"]
            where = f"{location['artifactLocation']['uri']}:{location['region']['startLine']}"
        except Exception:
            where = "(location unreadable)"
        rule = result.get("ruleId", "?") if isinstance(result, dict) else "?"
        verdict.blocking.append(f"potential secret: rule {rule} at {where}")
    return verdict


# -- Trivy --------------------------------------------------------------------------------------


def check_trivy(directory: Path, excepted: set[str], environ: Any = None) -> Verdict:
    environ = os.environ if environ is None else environ
    verdict = Verdict()
    for image, build_var, scan_var in TRIVY_IMAGES:
        build, scan = environ.get(build_var, "missing"), environ.get(scan_var, "missing")
        if build != "success":
            verdict.failures.append(f"{image}: the image was not built ({build}), so not scanned")
            continue
        if scan != "success":
            verdict.failures.append(f"{image}: the Trivy scan did not complete ({scan})")
            continue
        try:
            results = _json(directory / f"trivy-{image}.sarif")["runs"][0]["results"]
            if not isinstance(results, list):
                raise TypeError("results is not a list")
        except Exception as exc:
            verdict.failures.append(f"{image}: no valid Trivy report ({type(exc).__name__})")
            continue
        seen: set[str] = set()
        for result in results:
            if not isinstance(result, dict):
                verdict.failures.append(f"{image}: an unreadable Trivy result")
                continue
            rule, level = str(result.get("ruleId", "?")), str(result.get("level", "none"))
            if rule in seen:
                continue
            seen.add(rule)
            label = f"{image}: {rule} (SARIF level {level})"
            if level != "error":
                verdict.notes.append(label)
            elif rule in excepted:
                verdict.notes.append(f"{label} (excepted)")
            else:
                verdict.blocking.append(label)
    return verdict


CHECKS = {
    "pip-audit": check_pip_audit,
    "npm-audit": check_npm_audit,
    "gitleaks": check_gitleaks,
    "trivy": check_trivy,
}


def run(
    scanner: str, directory: Path, exceptions: Path, today: dt.date, out: Any = sys.stdout
) -> int:
    try:
        excepted, expired = load_exceptions(exceptions, scanner, today)
    except InvalidExceptionsError as exc:
        print(f"FAILED: the exceptions file is invalid: {exc}", file=out)
        return FAILED
    verdict = CHECKS[scanner](directory, excepted)
    verdict.notes.extend(expired)
    headline = {PASS: "PASS", FINDINGS: "BLOCKING FINDINGS", FAILED: "SCAN FAILED"}[verdict.code]
    print(f"{scanner}: {headline}", file=out)
    for line in verdict.failures:
        print(f"  failed: {line}", file=out)
    for line in verdict.blocking:
        print(f"  blocking: {line}", file=out)
    for line in verdict.notes:
        print(f"  reported: {line}", file=out)
    return verdict.code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scanner", choices=SCANNERS)
    parser.add_argument("--dir", type=Path, default=Path.cwd())
    parser.add_argument("--exceptions", type=Path, default=DEFAULT_EXCEPTIONS)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args(argv)
    return run(args.scanner, args.dir, args.exceptions, args.today)


if __name__ == "__main__":
    sys.exit(main())
