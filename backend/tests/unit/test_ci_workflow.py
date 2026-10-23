"""The CI workflow runs with least privilege and immutable action versions.

A tag such as `@v4` can be moved to different code by whoever controls the action's repository; a
full commit SHA cannot. The SHAs must be the same ones security.yml already reviewed, so the two
workflows never run different code for the same action.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
USES = re.compile(r"^\s*(?:- )?uses:\s*([\w.-]+/[\w./-]+)@(\S+)(.*)$", re.MULTILINE)


@pytest.fixture(scope="module")
def raw() -> str:
    return (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(raw: str) -> dict[str, Any]:
    return yaml.safe_load(raw)


def test_the_default_token_is_read_only(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}, name


def test_every_action_is_pinned_to_a_full_sha_with_a_version_comment(raw: str) -> None:
    uses = USES.findall(raw)

    assert len(uses) >= 10
    for action, ref, rest in uses:
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{action}@{ref} is not pinned to a commit"
        assert re.search(r"#\s*v\d+\.\d+(\.\d+)?", rest), f"{action} has no version comment"


def test_ci_and_security_scanning_pin_the_same_commit_for_the_same_action(raw: str) -> None:
    security = (WORKFLOWS / "security.yml").read_text(encoding="utf-8")
    pinned_by_security = {action: ref for action, ref, _ in USES.findall(security)}

    for action, ref, _ in USES.findall(raw):
        if action in pinned_by_security:
            assert ref == pinned_by_security[action], action


def test_no_workflow_uses_the_pull_request_target_trigger() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        assert "pull_request_target" not in path.read_text(encoding="utf-8"), path.name
