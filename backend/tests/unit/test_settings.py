"""Tests for app.config.Settings."""

import pytest
from pydantic import SecretStr

from app.config import Settings, get_settings

_ENV_KEYS = (
    "APP_NAME",
    "DEBUG",
    "DATABASE_URL",
    "REDIS_URL",
    "API_V1_PREFIX",
    "GROQ_API_KEY",
    "PRIMARY_LLM_MODEL",
    "FAST_LLM_MODEL",
    "SAFETY_LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
)


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensures ambient environment variables can't leak into a defaults test."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults(isolated_env: None) -> None:
    settings = Settings()
    assert settings.app_name == "AegisAI"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.redis_url.startswith("redis://")
    assert settings.groq_api_key is None
    assert settings.primary_llm_model == "openai/gpt-oss-120b"
    assert settings.fast_llm_model == "openai/gpt-oss-20b"
    assert settings.safety_llm_model == "openai/gpt-oss-safeguard-20b"
    assert settings.llm_timeout_seconds == 30.0
    assert settings.llm_max_retries == 2


def test_groq_api_key_is_not_exposed_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(groq_api_key=SecretStr("sk-super-secret-value"))

    assert "sk-super-secret-value" not in repr(settings)
    assert "sk-super-secret-value" not in str(settings.groq_api_key)
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "sk-super-secret-value"


def test_llm_settings_env_override(
    monkeypatch: pytest.MonkeyPatch, clear_settings_cache: None
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-from-env")
    monkeypatch.setenv("PRIMARY_LLM_MODEL", "custom/primary-model")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")

    settings = get_settings()

    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "sk-from-env"
    assert settings.primary_llm_model == "custom/primary-model"
    assert settings.llm_max_retries == 5


def test_settings_env_override(monkeypatch, clear_settings_cache) -> None:
    monkeypatch.setenv("APP_NAME", "CustomName")
    monkeypatch.setenv("DEBUG", "true")

    settings = get_settings()

    assert settings.app_name == "CustomName"
    assert settings.debug is True


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
