"""Static checks on the Kubernetes workloads' pod security (no cluster is involved)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
K8S = ROOT / "infra" / "kubernetes"
BACKEND_DOCKERFILE = ROOT / "Dockerfile"
# The workloads that run the backend image (built from the root Dockerfile).
BACKEND_IMAGE_WORKLOADS = ["backend-deployment.yaml", "migration-job.yaml"]
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


# -- the backend image's identity ------------------------------------------------------------
#
# Regression: the image used to end with `USER app` (a name, with a uid useradd picked). The
# kubelet cannot check a name against `runAsNonRoot`, so it refused to start both the backend
# Deployment and the migration Job (CreateContainerConfigError). These tests check the files
# only; they do not build the image or run a cluster.


def _backend_runtime_stage() -> str:
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    runtime = dockerfile.split("AS runtime", 1)[1]
    return re.sub(r"[ \t]*\\\n\s*", " ", runtime)  # join continued lines


def _backend_identity() -> tuple[int, int]:
    """The uid and gid the backend image runs as, after checking they are declared consistently."""
    runtime = _backend_runtime_stage()

    groups = re.findall(r"\bgroupadd --system --gid (\d+) app\b", runtime)
    users = re.findall(
        r"\buseradd --system --uid (\d+) --gid (\d+) --no-create-home app\b", runtime
    )
    final_users = re.findall(r"^USER (\S+)\s*$", runtime, re.M)
    assert len(groups) == 1, "the app group must be created once, with an explicit gid"
    assert len(users) == 1, "the app user must be created once, with an explicit uid and gid"
    assert final_users, "the runtime stage must set USER"

    gid = int(groups[0])
    uid, user_gid = (int(value) for value in users[0])
    # The last USER is what the container runs as; it must be the numbers, not the name.
    assert re.fullmatch(r"\d+:\d+", final_users[-1]), final_users[-1]
    final_uid, final_gid = (int(value) for value in final_users[-1].split(":"))

    assert (uid, user_gid) == (final_uid, final_gid) and user_gid == gid
    return uid, gid


def test_the_backend_image_runs_as_a_fixed_numeric_non_root_identity() -> None:
    uid, gid = _backend_identity()

    assert uid != 0 and gid != 0
    assert (uid, gid) == (10001, 10001)
    # Not a name: a non-numeric USER is exactly what the kubelet refuses under runAsNonRoot.
    assert "USER app" not in _backend_runtime_stage()


def test_the_fixed_identity_keeps_write_access_to_its_runtime_paths() -> None:
    runtime = _backend_runtime_stage()
    create = runtime.index("useradd --system")
    final_user = runtime.rindex("\nUSER ")

    # The ownership is given (by name, so to the fixed ids) after the user exists and while the
    # build still runs as root, i.e. before the final USER.
    for chown in ("chown -R app:app /srv", "chown -R app:app /home/app"):
        assert create < runtime.index(chown) < final_user, chown
    # HOME is the writable home, where the Hugging Face model cache goes ($HOME/.cache).
    assert "mkdir -p /home/app" in runtime
    assert "ENV HOME=/home/app" in runtime


@pytest.mark.parametrize("name", BACKEND_IMAGE_WORKLOADS)
def test_backend_image_workloads_take_the_user_from_the_image(name: str) -> None:
    spec = pod_spec(name)

    assert all(c["image"].startswith("aegisai-backend:") for c in spec["containers"])
    # As for the frontend: the image declares the numeric user, the manifests do not repeat it.
    contexts = [spec["securityContext"]] + [c["securityContext"] for c in spec["containers"]]
    for context in contexts:
        assert "runAsUser" not in context and "runAsGroup" not in context
    assert spec["securityContext"]["runAsNonRoot"] is True


def test_the_backend_volume_group_is_the_image_group() -> None:
    _, gid = _backend_identity()
    spec = pod_spec("backend-deployment.yaml")

    # The uploads volume is handed to this group, so the non-root process can write to it.
    assert spec["securityContext"]["fsGroup"] == gid
    assert spec["securityContext"]["fsGroupChangePolicy"] == "OnRootMismatch"
    mounts = {m["mountPath"] for c in spec["containers"] for m in c.get("volumeMounts", [])}
    assert "/data/uploads" in mounts


# -- the bundled Redis (upstream image) ------------------------------------------------------
#
# Regression: the Redis pod ran as root with every capability dropped, so the image's entrypoint
# could not switch to its `redis` user (`setpriv: setresuid failed`) and crash-looped in the
# first smoke run. It now starts as that user. Unlike the backend, the manifest names the uid:
# the upstream image has no USER. These check the manifest only, not a running Redis.
REDIS_UID = 999  # the official image's `redis` user
REDIS_GID = 1000  # and its `redis` group


def test_redis_runs_as_the_images_own_non_root_user() -> None:
    spec = pod_spec("redis-deployment.yaml")
    pod = spec["securityContext"]

    assert pod["runAsNonRoot"] is True
    assert pod["runAsUser"] == REDIS_UID != 0
    assert pod["runAsGroup"] == REDIS_GID != 0
    assert pod["seccompProfile"]["type"] == "RuntimeDefault"
    assert spec["automountServiceAccountToken"] is False
    (container,) = spec["containers"]
    assert container["image"].startswith("redis:")
    # Nothing in the container puts the user back to another one (or to root).
    for key in ("runAsUser", "runAsGroup", "runAsNonRoot"):
        assert key not in container["securityContext"], key


def test_redis_keeps_every_capability_dropped_and_adds_none() -> None:
    (container,) = pod_spec("redis-deployment.yaml")["containers"]
    context = container["securityContext"]

    assert context["allowPrivilegeEscalation"] is False
    assert context["capabilities"] == {"drop": ["ALL"]}  # exactly this: no `add` key at all
    assert context.get("privileged", False) is False
