# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem.

- Use GitHub's **private vulnerability reporting** for this repository (Security tab, "Report a
  vulnerability") if it is enabled.
- If it is not, contact the repository owner privately through their GitHub profile and share
  details only once they have replied.

Include what you found, how to reproduce it, and the version or commit. Never include real
credentials, tokens or personal data in a report.

This is a personal/learning project and has no service-level agreement; reports are handled on a
best-effort basis.

## What is monitored

Dependency, secret and container-image scans run on GitHub Actions in **reporting-only** mode (they
do not block merges yet). See [docs/operations/security-scanning.md](docs/operations/security-scanning.md)
for coverage, limits and how findings are triaged. The scans have **not yet been run**, so there is
no baseline of known findings.

## Supported versions

Only the current `main` branch.
