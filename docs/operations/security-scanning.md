# Security scanning

**Status: configured, reporting-only, has run, findings not yet reviewed.** GitHub's public run list
shows the workflow completing on `main` (run #37, commit `5d30825`, 2026-10-22). Because every job is
reporting-only, "completed successfully" only means the jobs finished: the findings are in the run
summaries and artifacts, which need a signed-in GitHub account and **have not been reviewed**. So there
is still **no reviewed baseline**, and this document does not claim the repository is free of
vulnerabilities or secrets. When a scan should start blocking is open decision D-9 in
[ADR 017](../architecture/decisions/017-open-decisions-and-residual-risks.md).

Files: `.github/workflows/security.yml`, `.github/dependabot.yml`, `.gitleaks.toml`, `SECURITY.md`.
`.github/workflows/ci.yml` is not a scanner; it now pins its actions to the same commit SHAs this
workflow reviewed and runs with a read-only token (`backend/tests/unit/test_ci_workflow.py`).

## What runs, and what it covers

| Job | Tool | Covers | Output |
|---|---|---|---|
| `python-audit` | `pip-audit` (version pinned in the workflow) | The Python packages pinned in `uv.lock`, exported twice: runtime only, and all groups (dev tools and the Streamlit group). Looks up known advisories; does not install anything. | `pip-audit-*.json` artifact, run summary |
| `npm-audit` | `npm audit` | `frontend/web/package-lock.json`: runtime dependencies only, and everything including build and test tooling. | `npm-audit-*.json` artifact, run summary |
| `secret-scan` | `gitleaks` (pinned release, checksum-verified) | The **whole Git history** and working tree, with the default rules plus `.gitleaks.toml`. Run with `--redact`: secret values are replaced in the log and the report. | `gitleaks.sarif` artifact, run summary (rule, file, line, commit only) |
| `image-scan` | Trivy (see below) | The three images built in the job (backend, React, Streamlit): operating-system and library vulnerabilities that have a fix available. | `trivy-*.sarif` artifact, run summary, and SARIF offered to GitHub code scanning |

Triggers: pull requests and pushes to `main`, a weekly schedule (Mondays 04:17 UTC, because new
advisories appear without code changes) and manual dispatch. Dependabot (`dependabot.yml`) opens
weekly update pull requests for `uv`, `npm`, GitHub Actions and the three Dockerfile directories; it
merges nothing.

## Reporting-only means

- Every job has `continue-on-error: true`, every scan command tolerates a non-zero exit, and Trivy
  and gitleaks run with `exit-code 0`. A finding never fails a run.
- **A green run is not a clean result.** Check the summary, not the colour.
- No blocking threshold is set on purpose: the existing baseline must be understood first.

## How outcomes are told apart

Each scan step saves how its tool ended (an `.exit` file, or the Trivy step's recorded `outcome`),
and each job's summary step cross-checks that against the report. The summary never crashes on a
bad entry, and a problem is also raised as a run annotation (`::warning`). The meanings:

| What the summary says | What happened | Is it a clean result? |
|---|---|---|
| `audit complete, no known vulnerabilities` / `Scan complete: no potential secrets` / `scan complete, no fixable vulnerabilities` | The tool finished, the report is valid and lists nothing. | Only in the sense "no known advisory or configured rule matched"; never proof that nothing exists. |
| `findings reported` (gitleaks: `Findings reported`) / `N finding(s)` | The tool finished and lists findings (ids, files and lines, never secret values). | No: triage them. |
| `N skipped (NOT audited)` (pip-audit) | A package could not be looked up (for example the `+cpu` torch build). It is listed with pip-audit's reason. | **No.** Skipped packages were not audited. |
| `INVALID AUDIT` | The input was unusable: the requirements export failed, listed fewer than `MIN_PACKAGES` pinned packages (empty or truncated), the report lists 0 packages, or the report is missing, unreadable or contradicts the exit status (for example pip-audit exited 1 but lists no vulnerability). | **No.** Nothing trustworthy was audited. |
| `FAILED or the scan is INCOMPLETE` (gitleaks) | gitleaks exited non-zero. With `--exit-code 0`, findings exit 0, so non-zero means the tool itself failed; gitleaks 8.30.1 still writes a report after a partial scan, so an empty report is **not** evidence of a clean scan. | **No.** |
| `did not run` / `no valid report` / `no report` | The status file or report is missing or malformed. | **No.** |
| `The image build did not succeed` / `The Trivy scan step did not succeed (outcome: ...)` | The build or scan step failed or was skipped. The three images are independent, so one failure does not stop the others, and a report from a failed step is not trusted. | **No.** |

Every "not clean" line contains the exact words `NOT a clean result` (or `INVALID AUDIT`). The
exit-status and requirement files are kept in the artifacts next to the reports.

## Where to read the results

1. The run page: each job writes a summary.
2. Artifacts on the run: `pip-audit-reports`, `npm-audit-reports`, `gitleaks-report`, `trivy-reports`.
3. The repository's Security tab, **only if** code scanning is enabled: the image job offers its SARIF
   there. That upload is allowed to fail (`continue-on-error`), and the artifact is the fallback.
   Whether code scanning is available for this repository is not known.

## Permissions

Workflow default: `contents: read`. Only `image-scan` also has `security-events: write`, to offer
SARIF. No job uses repository secrets (only the automatic token), and no scan sends repository
content to a third-party service: advisory and database lookups are read-only downloads.

## Trivy version (reviewed, pinned explicitly)

- **Action:** `aquasecurity/trivy-action` v0.36.0, pinned by commit SHA. In March 2026 the Trivy
  supply chain was compromised (GHSA-69fq-xp46-6x23 / CVE-2026-33634): a malicious Trivy v0.69.4,
  and every `trivy-action` release before 0.35.0 replaced with malicious code. v0.36.0 is after the
  fix, is an immutable GitHub release on a signed commit, and pins `setup-trivy` v0.2.6 (the patched
  version named in that advisory).
- **Binary:** `TRIVY_VERSION: v0.74.0`, passed through the action's `version:` input instead of the
  action's older default. It is an immutable release published after the fixes for the advisories
  published for `aquasecurity/trivy`: CVE-2026-54448 (0.71.0), CVE-2026-55092 (0.71.1) and
  CVE-2026-63328 (0.72.0). It is not one of the compromised 0.69.4 to 0.69.6.
- **Compatibility:** every Trivy option the action passes (`format`, `output`, `exit-code`,
  `scanners`, `ignore-unfixed`, cache directory) exists in Trivy v0.74.0's source and v0.36.0 has the
  same inputs as v0.35.0. This was read from the sources, **not run**.
- **Maintenance:** Dependabot does not track the `version:` input. Re-check upstream advisories when
  reviewing scan results and update it deliberately.
- **Not independently verified:** the cryptographic signatures of the Trivy release files.

## Known limitations and expected noise

- **torch**: it is installed from a CPU-only index, so its version carries a `+cpu` suffix that may
  not exist on PyPI. `pip-audit` then reports it as *skipped*, which means **not audited**. Check the
  skipped list in the summary.
- **Dev-only tooling** (vite, vitest, jsdom, oxlint, pytest) appears in the "all" scans; treat the
  runtime scans as the shipped surface.
- **Unfixed OS vulnerabilities** in base images are hidden (`ignore-unfixed`) so the report is
  actionable; they are therefore not reported at all.
- **Gitleaks** may flag test fixtures (the auth tests build fake tokens and keys at run time) or
  the development realm in `infra/keycloak/`. Only three files are allowlisted today (the
  environment template and the two Kubernetes Secret templates). Handle any other false positive by
  adding a single-file, justified entry after reviewing the finding, never a directory.
- Scanners find **known** issues only: not logic bugs, authorization mistakes or misconfiguration.
- Gitleaks scans the repository's commits, not anything that was never committed.
- The images are built from the current commit on the runner; images in a registry or a cluster are
  not scanned (none are published).
- Tool and action versions were looked up from their GitHub repositories at the time of writing but
  **not executed**; compatibility (for example `pip-audit` options, Trivy's database download from a
  rate-limited host) is verified only by the first run.

## Triage

1. Read the summary and artifacts of the first run. Record the counts here as the baseline.
2. For each finding: **fix** (upgrade, or remove the secret and **rotate it**: removing it from
   history does not make it safe), **accept** (write the reason and a review date below), or
   **ignore as a false positive** (single-file allowlist with a reason).
3. A leaked secret is an incident regardless of severity: rotate it first.
4. When the baseline is understood, propose a blocking rule (suggested: new high or critical findings
   with a fix available) in a separate change.

## Baseline log

| Date | Scan | Result | Decision |
|---|---|---|---|
| _not yet scanned_ | | | |
