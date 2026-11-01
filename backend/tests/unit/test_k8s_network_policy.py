"""Static checks for the data tier's network isolation and Redis authentication (AIGSEC-005).

Nothing is applied to a cluster: the manifests are parsed and checked against each other, so a
selector that matches no real pod, or a port that is not the container's, fails here. Whether the
cluster's network plugin enforces the policies is a deployment fact this cannot check (see
infra/kubernetes/README.md, "Network policies").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

MANIFESTS = Path(__file__).resolve().parents[3] / "infra" / "kubernetes"
NAME = "app.kubernetes.io/name"
DATA_TIER = {"aegisai-postgres": 5432, "aegisai-redis": 6379}


def _documents(filename: str) -> list[dict[str, Any]]:
    text = (MANIFESTS / filename).read_text(encoding="utf-8")
    return [doc for doc in yaml.safe_load_all(text) if doc]


def _policies() -> dict[str, dict[str, Any]]:
    docs = _documents("data-tier-network-policy.yaml")
    assert all(doc["kind"] == "NetworkPolicy" for doc in docs)
    return {doc["metadata"]["name"]: doc for doc in docs}


def _pod_labels() -> dict[str, dict[str, str]]:
    """Every workload's pod-template labels, keyed by the manifest file."""
    labels = {}
    for path in MANIFESTS.glob("*.yaml"):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if doc and doc.get("kind") in {"Deployment", "StatefulSet", "Job"}:
                labels[path.name] = doc["spec"]["template"]["metadata"]["labels"]
    return labels


def _container(filename: str) -> dict[str, Any]:
    (doc,) = [d for d in _documents(filename) if d["kind"] in {"Deployment", "StatefulSet"}]
    return doc["spec"]["template"]["spec"]["containers"][0]


def _selects(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    for key, value in selector.get("matchLabels", {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions", []):
        assert expression["operator"] == "In"
        if labels.get(expression["key"]) not in expression["values"]:
            return False
    return True


def test_the_three_policies_exist() -> None:
    assert set(_policies()) == {
        "aegisai-data-tier-default-deny",
        "aegisai-postgres-from-backend",
        "aegisai-redis-from-backend",
    }


def test_the_default_deny_covers_exactly_the_data_tier_and_allows_nothing() -> None:
    policy = _policies()["aegisai-data-tier-default-deny"]["spec"]
    selected = {
        labels[NAME] for labels in _pod_labels().values() if _selects(policy["podSelector"], labels)
    }

    assert selected == set(DATA_TIER)
    assert policy["policyTypes"] == ["Ingress"]  # egress, and so DNS, untouched
    assert policy["ingress"] == []


@pytest.mark.parametrize(
    ("policy_name", "target"),
    [
        ("aegisai-postgres-from-backend", "aegisai-postgres"),
        ("aegisai-redis-from-backend", "aegisai-redis"),
    ],
)
def test_only_backend_pods_may_reach_each_data_service_on_its_own_port(
    policy_name: str, target: str
) -> None:
    spec = _policies()[policy_name]["spec"]
    (rule,) = spec["ingress"]
    (source,) = rule["from"]
    (port,) = rule["ports"]

    assert spec["podSelector"] == {"matchLabels": {NAME: target}}
    # A pod selector alone: same namespace only, no namespace-wide or IP-range allowance.
    assert set(source) == {"podSelector"}
    assert source["podSelector"] == {"matchLabels": {NAME: "aegisai-backend"}}
    assert (port["protocol"], port["port"]) == ("TCP", DATA_TIER[target])


def test_the_selectors_match_real_pods_and_nothing_else() -> None:
    labels = _pod_labels()
    backend_pods = {
        name
        for name, pod in labels.items()
        if _selects({"matchLabels": {NAME: "aegisai-backend"}}, pod)
    }

    # The API server and the migration Job (which needs PostgreSQL); not the frontend.
    assert backend_pods == {"backend-deployment.yaml", "migration-job.yaml"}
    for target, port in DATA_TIER.items():
        (filename,) = [name for name, pod in labels.items() if pod[NAME] == target]
        ports = [p["containerPort"] for p in _container(filename)["ports"]]
        assert ports == [port], filename


def test_redis_takes_its_password_from_a_secret_reference() -> None:
    container = _container("redis-deployment.yaml")
    (variable,) = [v for v in container["env"] if v["name"] == "REDIS_PASSWORD"]
    script = container["args"][0]

    assert variable["valueFrom"]["secretKeyRef"] == {
        "name": "aegisai-redis-secret",
        "key": "REDIS_PASSWORD",
    }
    assert "value" not in variable  # never a literal
    assert 'if [ -z "$REDIS_PASSWORD" ]' in script and "exit 1" in script
    assert "--requirepass" not in script  # not visible in the process list
    assert "exec redis-server /tmp/redis.conf" in script


@pytest.mark.parametrize("probe", ["readinessProbe", "livenessProbe"])
def test_redis_probes_authenticate(probe: str) -> None:
    command = _container("redis-deployment.yaml")[probe]["exec"]["command"]

    assert command[:2] == ["sh", "-c"]
    assert 'REDISCLI_AUTH="$REDIS_PASSWORD"' in command[2]
    assert "grep -q PONG" in command[2]


def test_the_backend_authenticates_with_the_same_secret_key() -> None:
    container = _container("backend-deployment.yaml")
    (variable,) = [v for v in container["env"] if v["name"] == "REDIS_PASSWORD"]
    config = _documents("backend-configmap.yaml")[0]["data"]

    assert variable["valueFrom"]["secretKeyRef"] == {
        "name": "aegisai-redis-secret",
        "key": "REDIS_PASSWORD",
    }
    assert "@" not in config["REDIS_URL"]  # no credential inside the URL
    assert "REDIS_PASSWORD" not in config  # and none in the ConfigMap


def test_the_redis_secret_is_a_placeholder_template_only() -> None:
    (secret,) = _documents("redis-secret.example.yaml")

    assert secret["kind"] == "Secret"
    assert secret["metadata"]["name"] == "aegisai-redis-secret"
    assert secret["stringData"] == {"REDIS_PASSWORD": "REPLACE_ME_REDIS_PASSWORD"}


def test_no_manifest_carries_a_plaintext_redis_password() -> None:
    for path in MANIFESTS.glob("*.yaml"):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if not doc or doc.get("kind") == "Secret":
                continue
            for workload_container in (
                doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            ):
                for variable in workload_container.get("env", []):
                    if "PASSWORD" in variable["name"]:
                        assert "value" not in variable, (path.name, variable["name"])


def test_replicas_share_rate_limits_through_redis() -> None:
    # AIGSEC-008: switching pods must not reset a user's budget.
    config = _documents("backend-configmap.yaml")[0]["data"]

    assert config["RATE_LIMIT_BACKEND"] == "redis"
