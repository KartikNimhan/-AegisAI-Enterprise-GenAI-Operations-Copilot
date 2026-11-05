"""Static checks on the Debian package floors in the two Python runtime images.

The `python:3.12-slim` base shipped apt and libapt-pkg7.0 3.0.3 (CVE-2026-109518, HIGH; Trivy,
Security scanning #130), so both runtime stages upgrade exactly those two packages and then
require at least 3.0.4. The checks make the build fail instead of shipping an older version.

Regressions covered: the step being dropped, widened into a full upgrade (which would change
unrelated packages), losing a version check or the cleanup, or moving after the switch to the
unprivileged user (where apt cannot run).

These do NOT build an image: they prove the Dockerfiles say the right thing. Whether Debian
serves the fixed version, and Trivy's verdict, are checked by the CI image scan.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILES = ["Dockerfile", "frontend/streamlit/Dockerfile"]
PACKAGES = ["apt", "libapt-pkg7.0"]
FLOOR = "3.0.4"


def _runtime_stage(dockerfile: str) -> str:
    """The runtime stage, with `\\`-continued lines joined, so each RUN is one line."""
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    runtime = text.split("AS runtime", 1)[1]
    return re.sub(r"\s*\\\n\s*", " ", runtime)


def _run_steps(runtime: str) -> list[str]:
    """The RUN instructions only (comments may mention commands the image must not run)."""
    return [line for line in runtime.splitlines() if line.startswith("RUN ")]


def _apt_step(runtime: str) -> str:
    steps = [step for step in _run_steps(runtime) if "apt-get" in step]
    assert len(steps) == 1, steps
    return steps[0]


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_runtime_stage_upgrades_only_apt_and_libapt(dockerfile: str) -> None:
    runtime = _runtime_stage(dockerfile)
    step = _apt_step(runtime)

    assert "apt-get update" in step
    assert "--only-upgrade apt libapt-pkg7.0" in step
    # Never a blanket upgrade: it would replace unrelated packages of the base image.
    for blanket in ("apt-get upgrade", "apt-get dist-upgrade", "apt-get full-upgrade"):
        assert not any(blanket in run for run in _run_steps(runtime)), blanket


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_each_package_must_reach_the_floor(dockerfile: str, package: str) -> None:
    step = _apt_step(_runtime_stage(dockerfile))

    installed = f"dpkg-query --show --showformat='${{Version}}' {package}"
    check = f'dpkg --compare-versions "$({installed})"'
    assert f"{check} ge {FLOOR}" in step
    # Chained with `&&`, so a version below the floor fails the build.
    assert f"&& {check}" in step


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_package_lists_are_removed_after_the_checks(dockerfile: str) -> None:
    step = _apt_step(_runtime_stage(dockerfile))

    # The last command of the step, so it runs only after both version checks have passed.
    assert step.endswith("&& rm -rf /var/lib/apt/lists/*")


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_upgrade_runs_as_root_before_the_final_user(dockerfile: str) -> None:
    runtime = _runtime_stage(dockerfile)

    final_user = runtime.rindex("\nUSER ")
    assert runtime.index(_apt_step(runtime)) < final_user
    # The final user is not root.
    assert not re.match(r"USER (root|0)\b", runtime[final_user + 1 :])
