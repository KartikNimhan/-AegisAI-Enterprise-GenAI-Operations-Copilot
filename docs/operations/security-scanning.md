# Security scanning

**Status: configured, reporting-only, and never run.** The workflow, configuration and tests exist.
No scan has executed yet, so there is **no baseline of known findings**, and this document does not
claim the repository is free of vulnerabilities or secrets. The first workflow run is the first
evidence.

Files: `.github/workflows/security.yml`, `.github/dependabot.yml`, `.gitleaks.toml`, `SECURITY.md`.
The existing `.github/workflows/ci.yml` is unchanged.

## What runs, and what it covers

| Job | Tool | Covers | Output |
|---|---|---|---|
| `python-audit` | `pip-audit` (version pinned in the workflow) | The Python packages pinned in `uv.lock`, exported twice: runtime only, and all groups (dev tools and the Streamlit group). Looks up known advisories; does not install anything. | `pip-audit-*.json` artifact, run summary |
| `npm-audit` | `npm audit` | `frontend/web/package-lock.json`: runtime dependencies only, and everything including build and test tooling. | `npm-audit-*.json` artifact, run summary |
| `secret-scan` | `gitleaks` (pinned release, checksum-verified) | The **whole Git history** and working tree, with the default rules plus `.gitleaks.toml`. Run with `--redact`: secret values are replaced in the log and the report. | `gitleaks.sarif` artifact, run summary (rule, file, line, commit only) |
| `image-scan` | Trivy | The three images built in the job (backend, React, Streamlit): operating-system and library vulnerabilities that have a fix available. | `trivy-*.sarif` artifact, run summary, and SARIF offered to GitHub code scanning |

Triggers: pull requests and pushes to `main`, a weekly schedule (Mondays 04:17 UTC, because new
advisories appear without code changes) and manual dispatch. Dependabot (`dependabot.yml`) opens
weekly update pull requests for `uv`, `npm`, GitHub Actions and the three Dockerfile directories; it
merges nothing.

## Reporting-only means

- Every job has `continue-on-error: true`, every scan command tolerates a non-zero exit, and Trivy
  and gitleaks run with `exit-code 0`. A finding never fails a run.
- **A green run is not a clean result.** Each summary says explicitly when a report is missing
  ("this is NOT a clean result"). Check the summary, not the colour.
- No blocking threshold is set on purpose: the existing baseline must be understood first.

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
