"""Offline checks for the manual Kubernetes smoke-test workflow (`k8s-smoke.yml`).

The workflow deploys the committed infra/kubernetes/ manifests to a throwaway kind cluster. These
checks are about keeping it safe and honest: started by hand only, a read-only token, no secret or
job token, a checksum-verified kind and a digest-pinned node image, images built locally and never
pushed, test-only substitutions applied at run time (the committed manifests stay untouched), a
generated and masked password, bounded waits, diagnostics that never print Secret contents, the
cluster always deleted, and every layer of the stack actually checked. The substitutions are also
replayed here on the real manifests, and the result is put through the app's own start-up
validation. None of this runs the workflow; the first manual run on GitHub does that.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings
from tests.unit.test_rag_integration_workflow import secret_or_token_expressions

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOWS / "k8s-smoke.yml"
MANIFESTS = ROOT / "infra" / "kubernetes"
MIGRATIONS = ROOT / "backend" / "alembic" / "versions"
JOB = "smoke"
USES = re.compile(r"^\s*(?:- )?uses:\s*([\w.-]+/[\w./-]+)@(\S+)(.*)$", re.MULTILINE)
# `sed -e 's|old|new|'` (single- or double-quoted): the only kind of edit the workflow makes.
SED_EDIT = re.compile(r"""-e\s+(['"])s\|([^|]+)\|([^|]+)\|\1""")
APPLIED = {
    "postgres-statefulset",
    "postgres-service",
    "redis-deployment",
    "redis-service",
    "backend-configmap",
    "backend-pvc",
    "migration-job",
    "backend-deployment",
    "backend-service",
    "frontend-configmap",
    "frontend-deployment",
    "frontend-service",
}


@pytest.fixture(scope="module")
def raw() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(raw: str) -> dict[Any, Any]:
    return yaml.safe_load(raw)


@pytest.fixture(scope="module")
def job(workflow: dict[Any, Any]) -> dict[str, Any]:
    return workflow["jobs"][JOB]


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = [s for s in job["steps"] if s.get("name") == name]
    assert len(steps) == 1, f"expected exactly one step named {name!r}"
    return steps[0]


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def _render(job: dict[str, Any], workflow: dict[Any, Any], name: str) -> str:
    """The workflow's own substitutions, applied to a committed manifest the way the render step
    does (each `sed -e 's|old|new|'` replaces the first match on every line)."""
    script = _step(job, "Render the manifests with the test-only substitutions")["run"]
    text = (MANIFESTS / f"{name}.yaml").read_text(encoding="utf-8")
    edits = [
        (old, new.replace("${IMAGE_TAG}", workflow["env"]["IMAGE_TAG"]))
        for _quote, old, new in SED_EDIT.findall(script)
    ]
    targets = {"backend-configmap": [e for e in edits if "AUTH_" in e[0]]}
    for old, new in targets.get(name, [e for e in edits if "REPLACE_WITH_TAG" in e[0]]):
        text = "\n".join(line.replace(old, new, 1) for line in text.splitlines())
    return text


# -- structure ---------------------------------------------------------------------------------


def test_it_runs_only_when_started_by_hand(workflow: dict[Any, Any]) -> None:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = workflow[True] if True in workflow else workflow["on"]

    assert set(triggers) == {"workflow_dispatch"}
    assert not (triggers["workflow_dispatch"] or {}).get("inputs")  # nothing reaches the shell


def test_the_token_is_read_only(workflow: dict[Any, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    for name, each in workflow["jobs"].items():
        assert "permissions" not in each or each["permissions"] == {"contents": "read"}, name


def test_it_is_one_job_on_a_github_hosted_runner_with_a_30_minute_timeout(
    workflow: dict[Any, Any], job: dict[str, Any]
) -> None:
    assert set(workflow["jobs"]) == {JOB}
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 30
    assert workflow["concurrency"]["group"].startswith("k8s-smoke-")


def test_every_action_is_a_commit_ci_already_pins(raw: str) -> None:
    pinned_by_ci = dict(
        (action, ref)
        for action, ref, _ in USES.findall((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    )
    uses = USES.findall(raw)

    assert uses
    for action, ref, rest in uses:
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{action}@{ref} is not pinned to a commit"
        assert re.search(r"#\s*v\d+\.\d+(\.\d+)?", rest), f"{action} has no version comment"
        assert pinned_by_ci.get(action) == ref, f"{action} is not pinned to ci.yml's commit"


def test_the_checkout_does_not_keep_the_token(job: dict[str, Any]) -> None:
    checkouts = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]

    assert len(checkouts) == 1
    assert checkouts[0]["with"]["persist-credentials"] is False


def test_it_uses_no_secret_no_job_token_no_env_file_and_no_llm(
    raw: str, job: dict[str, Any]
) -> None:
    runs = _runs(job)

    assert secret_or_token_expressions(raw) == []
    assert "GITHUB_TOKEN" not in raw
    assert ".env" not in raw
    assert "GROQ" not in runs and "LLM" not in runs


def test_nothing_can_turn_a_failure_into_a_pass(job: dict[str, Any]) -> None:
    assert "continue-on-error" not in job and "if" not in job
    conditions = {step.get("name"): step.get("if") for step in job["steps"] if "if" in step}
    assert conditions == {
        "Show the cluster state after a failure": "${{ failure() }}",
        "Delete the kind cluster": "${{ always() }}",
    }
    assert all("continue-on-error" not in step for step in job["steps"])


def test_no_expression_is_expanded_into_a_shell(job: dict[str, Any]) -> None:
    assert all("${{" not in str(step.get("run", "")) for step in job["steps"])


# -- kind, images and manifests ----------------------------------------------------------------


def test_kind_is_a_pinned_release_verified_by_checksum(
    workflow: dict[Any, Any], job: dict[str, Any]
) -> None:
    env = workflow["env"]
    install = _step(job, "Install kind (checksum-verified)")["run"]

    assert re.fullmatch(r"v\d+\.\d+\.\d+", env["KIND_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["KIND_SHA256"])
    assert "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/" in install
    assert 'echo "${KIND_SHA256}  $RUNNER_TEMP/bin/kind" | sha256sum -c -' in install
    assert install.index("sha256sum -c") < install.index("chmod +x")
    assert re.fullmatch(r"kindest/node:v[\d.]+@sha256:[0-9a-f]{64}", env["KIND_NODE_IMAGE"])
    assert '--image "$KIND_NODE_IMAGE"' in _runs(job)


def test_the_images_are_built_here_loaded_into_kind_and_never_published(
    job: dict[str, Any], raw: str
) -> None:
    build = _step(job, "Build the backend and React images locally")["run"]
    runs = _runs(job)

    assert '--tag "aegisai-backend:${IMAGE_TAG}" --file Dockerfile .' in build
    assert (
        '--tag "aegisai-frontend:${IMAGE_TAG}" --file frontend/web/Dockerfile frontend/web' in build
    )
    assert "kind load docker-image" in runs
    for forbidden in (
        "docker push",
        "docker login",
        "push: true",
        "ghcr.io",
        "docker/login-action",
    ):
        assert forbidden not in raw.lower(), forbidden
    assert "registry" not in runs.lower()


def test_only_committed_manifests_are_applied_never_the_templates(job: dict[str, Any]) -> None:
    render = _step(job, "Render the manifests with the test-only substitutions")["run"]
    referenced = set(re.findall(r"\b([a-z]+(?:-[a-z]+)+)\b", render)) & {
        p.stem for p in MANIFESTS.glob("*.yaml")
    }

    assert referenced == APPLIED
    assert all((MANIFESTS / f"{name}.yaml").is_file() for name in APPLIED)
    assert ".example" not in _runs(job)  # the Secret templates and the ingress template


def test_the_substitutions_are_test_only_and_leave_the_committed_manifests_alone(
    workflow: dict[Any, Any], job: dict[str, Any]
) -> None:
    render = _step(job, "Render the manifests with the test-only substitutions")["run"]
    edits = SED_EDIT.findall(render)

    # Exactly the image tag and the three authentication settings, nothing else.
    assert sorted(old for _q, old, _new in edits) == sorted(
        [":REPLACE_WITH_TAG", 'AUTH_ISSUER: ""', 'AUTH_AUDIENCE: ""', 'AUTH_JWKS_URL: ""']
    )
    for _q, old, new in edits:
        if old.startswith("AUTH_") and "://" in new:
            assert re.search(r"https://[a-z-]+\.invalid/", new), new  # a reserved, unusable name
    # Every write goes to the copies under $RUNNER_TEMP, never into infra/kubernetes/.
    assert '> "$out/' in render
    assert not re.search(r">\s*\"?infra/", _runs(job))
    assert "sed -i" not in _runs(job)
    for path in MANIFESTS.glob("*.yaml"):
        assert ".invalid" not in path.read_text(encoding="utf-8"), path.name
    for name in ("migration-job", "backend-deployment", "frontend-deployment"):
        rendered = _render(job, workflow, name)
        assert "REPLACE_WITH_TAG" not in rendered, name
        assert f":{workflow['env']['IMAGE_TAG']}" in rendered, name


def test_the_rendered_backend_config_passes_the_apps_own_start_up_check(
    workflow: dict[Any, Any], job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def settings_from(configmap_text: str) -> Settings:
        data = yaml.safe_load(configmap_text)["data"]
        for key, value in data.items():
            monkeypatch.setenv(key, str(value))
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+asyncpg://aegis:pw@aegisai-postgres:5432/aegis"
        )
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("METRICS_TOKEN", raising=False)
        return Settings(_env_file=None)  # type: ignore[call-arg]

    rendered = settings_from(_render(job, workflow, "backend-configmap"))
    assert rendered.environment == "kubernetes"  # the real, non-local start-up path
    rendered.validate_for_serving()  # would raise if the backend refused to start

    committed = settings_from((MANIFESTS / "backend-configmap.yaml").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="Authentication is not configured"):
        committed.validate_for_serving()  # why the placeholders are needed at all


def test_the_secrets_come_from_a_generated_masked_password(job: dict[str, Any]) -> None:
    script = _step(job, "Create disposable Secrets from a generated password")["run"]

    assert 'password="$(openssl rand -hex 24)"' in script
    assert script.index('echo "::add-mask::${password}"') < script.index("kubectl create secret")
    assert "kubectl create secret generic aegisai-postgres-secret" in script
    assert "kubectl create secret generic aegisai-backend-secret" in script
    assert "--from-file" not in script


# -- what is checked, and how ------------------------------------------------------------------


def test_every_layer_of_the_stack_is_checked(job: dict[str, Any]) -> None:
    runs = _runs(job)

    for check in (
        "wait_rollout statefulset/aegisai-postgres",
        "pg_isready -U aegis -d aegis",
        "wait_rollout deployment/aegisai-redis",
        'redis-cli ping)" = "PONG"',
        "wait_job aegisai-migrate",
        "FROM pg_extension WHERE extname = 'vector'",
        "SELECT version_num FROM alembic_version",
        "wait_rollout deployment/aegisai-backend",
        'check_http http://127.0.0.1:18000/health/ready 200 \'"status":"ready"\'',
        "wait_rollout deployment/aegisai-frontend",
        "check_http http://127.0.0.1:18080/ 200 '<div id=\"root\"></div>'",
        'check_http http://127.0.0.1:18080/health 200 \'"status":"ok"\'',
        "check_http http://127.0.0.1:18080/api/v1/auth/me 401",
    ):
        assert check in runs, check


def test_the_expected_alembic_head_is_the_newest_migration(workflow: dict[Any, Any]) -> None:
    revisions = {}
    for path in MIGRATIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision: str = "([^"]+)"', text, re.MULTILINE)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', text, re.MULTILINE)
        if revision and down:
            revisions[revision.group(1)] = down.group(1)
    heads = set(revisions) - set(revisions.values())

    assert heads == {workflow["env"]["EXPECTED_ALEMBIC_HEAD"]}


def test_every_wait_is_bounded(job: dict[str, Any]) -> None:
    lib = _step(job, "Write the wait helpers")["run"]
    runs = _runs(job)

    assert "kind create cluster" in runs and "--wait 180s" in runs
    assert re.findall(r"kubectl rollout status [^\n]*", runs) == [
        'kubectl rollout status "$1" --timeout=10s >/dev/null 2>&1; do'
    ]
    assert "kubectl wait" not in runs
    assert lib.count('"$SECONDS" -ge "$deadline"') == 2  # wait_rollout and wait_job
    assert "--max-time 10" in lib and "for i in $(seq 1 30)" in lib
    # Every wait names its own limit in seconds.
    assert all(
        re.search(r" \d+$", line)
        for line in runs.splitlines()
        if re.match(r"\s*(wait_rollout|wait_job) ", line)
    )


def test_failure_diagnostics_never_print_secret_contents(job: dict[str, Any]) -> None:
    diagnostics = _step(job, "Show the cluster state after a failure")["run"]

    assert "kubectl get events" in diagnostics and "kubectl logs" in diagnostics
    assert "secret" not in diagnostics.lower()
    assert not re.search(r"-o\s*(yaml|json)", diagnostics)


def test_the_cluster_is_always_deleted_last(job: dict[str, Any]) -> None:
    last = job["steps"][-1]

    assert last["name"] == "Delete the kind cluster"
    assert last["if"] == "${{ always() }}"
    assert 'kind delete cluster --name "$CLUSTER_NAME"' in last["run"]
