"""Static checks on the Kubernetes workloads' pod security (no cluster is involved)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

K8S = Path(__file__).resolve().parents[3] / "infra" / "kubernetes"
WORKLOADS = [
    "backend-deployment.yaml",
    "frontend-deployment.yaml",
    "migration-job.yaml",
    "redis-deployment.yaml",
    "postgres-statefulset.yaml",
]
# The images this project builds; they are designed to run unprivileged.
APPLICATION_WORKLOADS = [
    "backend-deployment.yaml",
    "frontend-deployment.yaml",
    "migration-job.yaml",
]


def pod_spec(name: str) -> dict[str, Any]:
    return yaml.safe_load((K8S / name).read_text(encoding="utf-8"))["spec"]["template"]["spec"]


@pytest.mark.parametrize("name", WORKLOADS)
def test_no_pod_gets_a_service_account_token(name: str) -> None:
    # None of these talks to the Kubernetes API; a mounted token would only help an attacker.
    assert pod_spec(name)["automountServiceAccountToken"] is False


@pytest.mark.parametrize("name", APPLICATION_WORKLOADS)
def test_application_pods_run_unprivileged(name: str) -> None:
    spec = pod_spec(name)

    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    for container in spec["containers"]:
        context = container["securityContext"]
        assert context["allowPrivilegeEscalation"] is False
        assert context["capabilities"]["drop"] == ["ALL"]
        assert "privileged" not in context or context["privileged"] is False


@pytest.mark.parametrize("name", WORKLOADS)
def test_no_pod_uses_the_host_namespaces(name: str) -> None:
    spec = pod_spec(name)

    for key in ("hostNetwork", "hostPID", "hostIPC"):
        assert not spec.get(key, False), key
