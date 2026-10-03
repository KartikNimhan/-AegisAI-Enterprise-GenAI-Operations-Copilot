"""Application configuration loaded from environment variables / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AegisAI"
    environment: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Defaults match docker-compose.yml's host-mapped ports (5433/6380),
    # chosen to avoid colliding with any locally installed Postgres/Redis.
    database_url: str = "postgresql+asyncpg://aegis:aegis@localhost:5433/aegis"
    redis_url: str = "redis://localhost:6380/0"

    cors_origins: list[str] = ["http://localhost:8501"]

    # LLM Gateway (Groq). GROQ_API_KEY is deliberately optional so the app
    # starts and the test suite runs without one — calls through the
    # gateway fail with a typed LLMAuthenticationError until it's set.
    groq_api_key: SecretStr | None = None
    primary_llm_model: str = "openai/gpt-oss-120b"
    fast_llm_model: str = "openai/gpt-oss-20b"
    safety_llm_model: str = "openai/gpt-oss-safeguard-20b"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # Document ingestion (Milestone 3). Stored outside backend/app on
    # purpose — see app.storage. document_allowed_types holds raw strings
    # (not DocumentType) so this module stays free of any domain import;
    # app.documents.validation is what maps/validates them against
    # DocumentType.
    document_storage_dir: str = str(_REPO_ROOT / "data" / "uploads")
    document_max_upload_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    document_chunk_size: int = 1000  # characters, not tokens — see ADR 005
    document_chunk_overlap: int = 150  # characters
    document_allowed_types: list[str] = ["pdf", "docx", "txt", "markdown"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
