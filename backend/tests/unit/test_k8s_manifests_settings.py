"""The committed Kubernetes ConfigMap must be loadable by `Settings`.

Regression: the ConfigMap once named the backend by its Service DNS name over
plain http, which the settings validator rejects outside local development, so
the API pod and the migration Job would have failed at startup. Nothing
exercised the manifests against the code that consumes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings

_CONFIGMAP = Path(__file__).resolve().parents[3] / "infra" / "kubernetes" / "backend-configmap.yaml"
_AUTH_KEYS = ("AUTH_ISSUER", "AUTH_AUDIENCE", "AUTH_JWKS_URL")


def _config_data() -> dict[str, Any]:
    return yaml.safe_load(_CONFIGMAP.read_text(encoding="utf-8"))["data"]


def _settings_from(data: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key in list(data) + ["DATABASE_URL"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in data.items():
        monkeypatch.setenv(key, str(value))
    # The Secret supplies the real value in the cluster.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_backend_configmap_loads_as_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings_from(_config_data(), monkeypatch)

    assert settings.environment == "kubernetes"
    assert settings.debug is False
    assert settings.trusted_a2a_agents == ["http://localhost:8000"]


def test_the_configmap_declares_the_auth_keys_but_no_default_identity_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _config_data()
    assert all(key in data for key in _AUTH_KEYS)

    settings = _settings_from(data, monkeypatch)

    # Unset by design: the API refuses to serve until an operator fills them in.
    assert not settings.auth_configured
    with pytest.raises(Exception, match="AUTH_ISSUER"):
        settings.validate_for_serving()


def test_the_configmap_works_once_auth_values_are_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _config_data() | {
        "AUTH_ISSUER": "https://idp.example.test/realms/aegis",
        "AUTH_AUDIENCE": "aegisai-api",
        "AUTH_JWKS_URL": "https://idp.example.test/realms/aegis/protocol/openid-connect/certs",
    }

    _settings_from(data, monkeypatch).validate_for_serving()
