"""Static checks on the frontend image's nginx config and the files that must
agree with it (Dockerfile, Compose, Kubernetes).

Regressions covered:
- `/health` used to fall through to the SPA fallback in the same-origin setup,
  so the browser got index.html (HTTP 200, not JSON) and the top-bar indicator
  could never show the backend as up.
- The Kubernetes frontend asked for `runAsNonRoot` and dropped all capabilities
  while the image was stock nginx (root, port 80), which a cluster would refuse.

These do NOT run nginx or Kubernetes: they prove the configuration is
consistent, not that it works at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_WEB = _ROOT / "frontend" / "web"
_K8S = _ROOT / "infra" / "kubernetes"
_PORT = 8080


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(_text(path))


def _locations(template: str) -> list[tuple[str, str, str]]:
    """(modifier, path, body) for each top-level `location` block."""
    found = []
    for match in re.finditer(r"^    location (= )?(\S+) \{\n(.*?)^    \}", template, re.M | re.S):
        found.append(("=" if match.group(1) else "", match.group(2), match.group(3)))
    return found


def _resolve(template: str, request_path: str) -> str:
    """The body of the location nginx would pick: an exact match wins, else the
    longest matching prefix (no regex locations are used in this template)."""
    locations = _locations(template)
    for modifier, path, body in locations:
        if modifier == "=" and path == request_path:
            return body
    prefixes = [(p, b) for m, p, b in locations if m == "" and request_path.startswith(p)]
    assert prefixes, f"no location matches {request_path}"
    return max(prefixes, key=lambda item: len(item[0]))[1]


@pytest.fixture(scope="module")
def template() -> str:
    return _text(_WEB / "nginx.conf.template")


# -- B1: /health is proxied, not answered by the SPA fallback ------------------------


def test_health_is_proxied_to_the_backend_not_served_by_the_spa_fallback(template: str) -> None:
    body = _resolve(template, "/health")

    assert "proxy_pass ${BACKEND_UPSTREAM};" in body
    assert "try_files" not in body


def test_only_the_exact_health_path_is_proxied_not_its_siblings(template: str) -> None:
    # Readiness reports dependency state and is not exposed through the frontend.
    for path in ("/health/ready", "/healthz", "/health/"):
        assert "proxy_pass" not in _resolve(template, path), path


def test_the_api_proxy_and_the_spa_fallback_are_unchanged(template: str) -> None:
    assert "proxy_pass ${BACKEND_UPSTREAM};" in _resolve(template, "/api/v1/documents")
    assert "client_max_body_size 21m;" in _resolve(template, "/api/v1/documents")
    for spa_route in ("/", "/documents", "/operations", "/system", "/anything/else"):
        assert "try_files $uri $uri/ /index.html;" in _resolve(template, spa_route), spa_route
    assert "no-store" in _resolve(template, "/config.js")


def test_proxy_rules_forward_the_original_path(template: str) -> None:
    # A URI after the upstream would rewrite the path; none may be present.
    assert re.findall(r"proxy_pass (\S+);", template) == ["${BACKEND_UPSTREAM}"] * 2


# -- B2: non-root image, port 8080 everywhere ------------------------------------------


def test_nginx_listens_on_the_unprivileged_port(template: str) -> None:
    assert re.findall(r"^\s*listen (\S+);", template, re.M) == [str(_PORT)]


def test_dockerfile_uses_a_pinned_unprivileged_image_and_a_numeric_user() -> None:
    dockerfile = _text(_WEB / "Dockerfile")
    runtime = dockerfile[dockerfile.index("AS runtime") - 120 :]

    image = re.search(r"^FROM (\S+) AS runtime", dockerfile, re.M)
    assert image is not None
    assert image.group(1).startswith("nginxinc/nginx-unprivileged:")
    assert not image.group(1).endswith((":latest", ":alpine"))  # pinned to a version
    # The last USER in the file is what the container runs as: numeric, not root.
    users = re.findall(r"^USER (\S+)", dockerfile, re.M)
    assert users[-1] == "101"
    assert f"EXPOSE {_PORT}" in dockerfile
    assert f"http://127.0.0.1:{_PORT}/" in runtime
    # config.js is written at start without root, so its directory must be writable.
    assert "chown 101:0 /usr/share/nginx/html" in dockerfile


def test_compose_maps_and_probes_the_unprivileged_port() -> None:
    frontend = _yaml(_ROOT / "docker-compose.yml")["services"]["frontend"]

    assert frontend["ports"] == [f"3000:{_PORT}"]
    assert frontend["healthcheck"]["test"][-1] == f"http://127.0.0.1:{_PORT}/"


def test_kubernetes_frontend_uses_the_port_and_keeps_the_strict_security_context() -> None:
    deployment = _yaml(_K8S / "frontend-deployment.yaml")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert container["ports"] == [{"name": "http", "containerPort": _PORT}]
    for probe in ("livenessProbe", "readinessProbe"):
        assert container[probe]["httpGet"]["port"] == "http"  # the named port
    # Not weakened to accommodate the image.
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert "runAsUser" not in pod["securityContext"]
    assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert "add" not in container["securityContext"]["capabilities"]


def test_kubernetes_service_targets_the_named_container_port() -> None:
    service = _yaml(_K8S / "frontend-service.yaml")

    (port,) = service["spec"]["ports"]
    assert port["port"] == 80
    assert port["targetPort"] == "http"  # resolves to the container's 8080


def test_the_frontend_configmap_matches_the_template_variables(template: str) -> None:
    data = _yaml(_K8S / "frontend-configmap.yaml")["data"]

    assert set(data) == {"API_BASE_URL", "BACKEND_UPSTREAM"}
    assert data["API_BASE_URL"] == ""  # same origin
    assert "${BACKEND_UPSTREAM}" in template
