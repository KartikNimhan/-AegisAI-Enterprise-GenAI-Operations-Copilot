"""Application configuration loaded from environment variables / .env."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Asymmetric signature algorithms only. HMAC (HS*) and "none" are never
# acceptable for tokens verified with a published key set — see ADR/plan for M12.
ALLOWED_AUTH_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MIN_METRICS_TOKEN_CHARS = 16


_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f\\]")


def _check_url(name: str, value: str, *, require_https: bool) -> None:
    if _UNSAFE_URL_CHARS.search(value):
        raise ValueError(f"{name} must not contain whitespace, control characters or backslashes")
    try:
        parsed = urlparse(value)
        port = parsed.port  # raises ValueError for an unparsable or out-of-range port
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid URL") from exc
    if port == 0:
        raise ValueError(f"{name} must not use port 0")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{name} must be an http(s) URL with a host")
    if require_https and parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"{name} must use https outside local development (plain http is only "
            "allowed for loopback hosts)"
        )


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

    # http://localhost:8501 is the legacy Streamlit UI; :3000 is the React
    # app's Docker-published port; :5173 is Vite's local dev server.
    cors_origins: list[str] = [
        "http://localhost:8501",
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # LLM Gateway (Groq). GROQ_API_KEY is deliberately optional so the app
    # starts and the test suite runs without one — calls through the
    # gateway fail with a typed LLMAuthenticationError until it's set.
    groq_api_key: SecretStr | None = None
    primary_llm_model: str = "openai/gpt-oss-120b"
    fast_llm_model: str = "openai/gpt-oss-20b"
    safety_llm_model: str = "openai/gpt-oss-safeguard-20b"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    # Largest request body the API will read (bytes), whatever its Content-Type. The one
    # exception is the document upload route: DOCUMENT_MAX_UPLOAD_SIZE_BYTES plus 1 MiB of
    # multipart framing. The largest legitimate JSON request is analyst evidence.
    max_request_body_bytes: int = 16 * 1024 * 1024
    # A stream can trickle for as long as the provider keeps it open; the per-request timeout only
    # bounds waiting for data. This bounds the whole stream (seconds), then it fails as a timeout.
    llm_stream_total_timeout_seconds: float = 300.0

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
    # What a small file may EXPAND to (the upload limit only bounds the file itself): a DOCX's total
    # decompressed size, a PDF's page count, and the size of the extracted text of any format.
    # Exceeding one fails that document with a clear message (ADR 016).
    document_max_uncompressed_bytes: int = 64 * 1024 * 1024
    document_max_pdf_pages: int = 2_000
    document_max_extracted_chars: int = 20_000_000

    # Embeddings (Milestone 4). embedding_model_version is an
    # application-level label (not the HF revision hash) — it exists so we
    # can mark a "new generation" of vectors even without changing
    # embedding_model (e.g. if normalization or pooling logic changes),
    # since model name + version together are what's stored per-vector and
    # is what future model migration keys off. See ADR 006
    # (006-embedding-model.md).
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_version: str = "1"
    embedding_dimension: int = 384
    embedding_batch_size: int = 32
    embedding_device: str = "cpu"
    embedding_normalize: bool = True
    embedding_max_retries: int = 2

    # RAG (Milestone 5). rag_similarity_threshold is a cosine SIMILARITY
    # (1 - cosine_distance), not a raw distance — see ADR 007. The default
    # is a conservative starting point, not a scientifically validated
    # universal value: the correct threshold depends on the embedding
    # model, normalization, corpus, and query distribution, and should be
    # tuned against real usage. rag_max_results is a hard ceiling a
    # client's `top_k` override cannot exceed, independent of the default.
    rag_top_k: int = 5
    rag_max_results: int = 20
    rag_similarity_threshold: float = 0.3
    rag_max_context_chars: int = 8000

    # Agents (Milestone 6). Conservative development defaults, not
    # production-tuned claims — see ADR 008. agent_max_steps bounds the
    # number of agent/LLM turns in one run (each tool-call round trip is
    # one step); agent_max_tool_calls bounds total tool invocations across
    # the whole run, independent of step count (a single step can request
    # more than one tool call); agent_timeout_seconds is a wall-clock
    # backstop covering the entire run, not any single LLM/tool call.
    agent_max_steps: int = 8
    agent_max_tool_calls: int = 10
    agent_timeout_seconds: float = 60.0

    # Conversation history replayed into prompts (ADR 016): a window of the most recent messages
    # within BOTH limits (characters stand in for tokens). Older turns stay stored, just not sent.
    chat_history_max_messages: int = 40
    chat_history_max_chars: int = 24_000

    # Agent memory (ADR 015). Facts and preferences the agent keeps about ONE user across
    # conversations; private to that user, never shared. Every limit is a hard bound:
    # per item (chars), per user (rows), per run (writes), per prompt (items and chars), and a
    # time-to-live after which an unused note is no longer recalled and is purged on next write.
    agent_memory_enabled: bool = True
    agent_memory_max_item_chars: int = 500
    agent_memory_max_items_per_user: int = 200
    agent_memory_max_writes_per_run: int = 3
    agent_memory_max_recalled: int = 8
    agent_memory_max_prompt_chars: int = 2000
    agent_memory_ttl_days: int = 90

    # MCP (Milestone 7). The in-process MCP server's capabilities are
    # exposed to the agent only through an explicit allowlist — a
    # discovered tool is never trusted just because the server returned
    # it. trusted_mcp_servers names approved server identities (this
    # project runs exactly one, in-process); trusted_mcp_tools is the
    # tool-name allowlist checked against every discovered tool before it
    # is ever registered. See ADR 009.
    mcp_client_timeout_seconds: float = 10.0
    trusted_mcp_servers: list[str] = ["aegisai-internal"]
    trusted_mcp_tools: list[str] = [
        "search_knowledge_base",
        "calculator",
        "get_document_metadata",
    ]

    # A2A (Milestone 7). trusted_a2a_agents is a base-URL allowlist — the
    # orchestrator may only fetch an Agent Card from, and submit a task
    # to, a configured URL, never one supplied by a user or discovered at
    # runtime. research_agent_name is checked against the fetched card's
    # `name` as a second, independent trust signal before any capability
    # on it is used. The Research Agent in this milestone happens to be
    # served by this same application (see ADR 009) — the allowlist still
    # enforces the real A2A trust boundary, not an implementation detail.
    a2a_client_timeout_seconds: float = 15.0
    # Hard bounds on one exchange with a (trusted, but fallible) agent: the response body is read
    # incrementally and refused above the byte cap, and the whole exchange (card + task) has a
    # deadline on top of the per-phase HTTP timeout, which a slow-drip response would never trip.
    a2a_max_response_bytes: int = 1_048_576
    a2a_total_timeout_seconds: float = 30.0
    trusted_a2a_agents: list[str] = ["http://localhost:8000"]
    research_agent_name: str = "AegisAI Research Agent"
    document_agent_name: str = "AegisAI Document Agent"
    analyst_agent_name: str = "AegisAI Analyst Agent"

    # Multi-agent orchestration (Milestone 8). multi_agent_timeout_seconds
    # bounds the whole workflow (checked at each tier boundary, not via
    # hard mid-flight task cancellation — see ADR 010, "Cancellation");
    # multi_agent_agent_timeout_seconds bounds a single specialist call
    # (including its own retries). multi_agent_max_retries only ever
    # retries a transient A2A failure (connection/timeout), never a
    # validation/authorization/task failure. max_agent_depth and
    # max_agent_delegations are defense-in-depth loop guards: this
    # milestone's orchestrator never lets a specialist delegate further on
    # its own, so depth is always 1 in practice today, but the limits are
    # still enforced so a future agent-to-agent delegation can't silently
    # become unbounded.
    multi_agent_timeout_seconds: float = 45.0
    multi_agent_agent_timeout_seconds: float = 20.0
    multi_agent_max_retries: int = 1
    max_agent_depth: int = 2
    max_agent_delegations: int = 5

    # Authentication (Milestone 12, Phase 1a). The API is an OIDC *resource
    # server*: it verifies bearer access tokens and holds no passwords or
    # signing secrets (only public keys, fetched from auth_jwks_url).
    # auth_issuer must equal the token's `iss` EXACTLY — with Keycloak that is
    # the URL the browser used, which can differ from the URL the backend uses
    # to reach it, so the key-set URL is a separate setting. Required
    # (together with auth_audience) whenever environment != "local"; unset
    # locally means every protected route fails closed with 503.
    # Outside "local" these must be https (loopback hosts excepted).
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_jwks_url: str | None = None
    auth_allowed_algorithms: list[str] = ["RS256"]
    auth_leeway_seconds: int = 30
    auth_jwks_cache_seconds: int = 600
    auth_jwks_min_refresh_seconds: float = 30.0
    auth_jwks_timeout_seconds: float = 5.0
    # After a failed (or malformed) key-set fetch, further fetches are refused
    # for this many seconds so an outage cannot make every request wait on the
    # network. 0 disables the circuit breaker.
    auth_jwks_failure_cooldown_seconds: float = 5.0

    # Rate limits (see app/core/rate_limit.py). Per authenticated user, in a sliding window,
    # enforced in memory PER PROCESS (not shared between workers or replicas). A limit of 0
    # switches that one bucket off; rate_limit_enabled=false switches all of them off. The
    # numbers below are starting points for you to review, not recommendations.
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_llm_requests: int = 30
    rate_limit_document_uploads: int = 10
    rate_limit_embedding_jobs: int = 5
    # Upper bound on (bucket, user) counters held in memory; if it is reached with every entry still
    # live the limiter fails closed (503) instead of letting requests through unmetered.
    rate_limit_max_tracked_keys: int = 100_000

    # Application metrics (app.observability). OFF by default: nothing is recorded or exposed.
    # When enabled, GET /metrics is served outside the OIDC-protected API and requires
    # `Authorization: Bearer <METRICS_TOKEN>`; outside local development the API refuses to start
    # without a token (see `validate_for_serving`). The token is a secret: never log or return it.
    metrics_enabled: bool = False
    metrics_token: SecretStr | None = None

    @field_validator("auth_issuer", "auth_audience", "auth_jwks_url", mode="before")
    @classmethod
    def _blank_auth_value_is_unset(cls, value: object) -> object:
        # docker-compose passes unset variables through as empty strings.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_auth_settings(self) -> Self:
        algorithms = self.auth_allowed_algorithms
        if not algorithms or any(a not in ALLOWED_AUTH_ALGORITHMS for a in algorithms):
            raise ValueError(
                "AUTH_ALLOWED_ALGORITHMS may only contain asymmetric algorithms "
                f"({', '.join(sorted(ALLOWED_AUTH_ALGORITHMS))}); HMAC and 'none' are never allowed"
            )
        if not 0 <= self.auth_leeway_seconds <= 60:
            raise ValueError("AUTH_LEEWAY_SECONDS must be between 0 and 60")
        if self.auth_jwks_cache_seconds <= 0 or self.auth_jwks_timeout_seconds <= 0:
            raise ValueError("AUTH_JWKS_CACHE_SECONDS and AUTH_JWKS_TIMEOUT_SECONDS must be > 0")
        if self.auth_jwks_min_refresh_seconds < 0:
            raise ValueError("AUTH_JWKS_MIN_REFRESH_SECONDS must be >= 0")
        if not 0 <= self.auth_jwks_failure_cooldown_seconds <= 60:
            raise ValueError("AUTH_JWKS_FAILURE_COOLDOWN_SECONDS must be between 0 and 60")

        non_local = self.environment != "local"
        if non_local and self.debug:
            # DEBUG turns on verbose behavior (SQL statement logging with bound
            # parameters, among others) that must never run outside local.
            raise ValueError(
                f"DEBUG must be false when ENVIRONMENT={self.environment!r} (it is only "
                "allowed in local development)"
            )
        # NOTE: whether authentication is *configured at all* is deliberately NOT
        # checked here — Alembic, scripts and the evaluation CLI load Settings
        # too and do not serve requests. That requirement is enforced when the
        # API is built (see `validate_for_serving`, called from `app.main`).
        if self.auth_issuer:
            _check_url("AUTH_ISSUER", self.auth_issuer, require_https=non_local)
        if self.auth_jwks_url:
            _check_url("AUTH_JWKS_URL", self.auth_jwks_url, require_https=non_local)
        if non_local:
            # The caller's bearer token is forwarded to these agents.
            for agent_url in self.trusted_a2a_agents:
                _check_url("TRUSTED_A2A_AGENTS entry", agent_url, require_https=True)
        return self

    @model_validator(mode="after")
    def _validate_rate_limits(self) -> Self:
        if not 1 <= self.rate_limit_window_seconds <= 86_400:
            raise ValueError("RATE_LIMIT_WINDOW_SECONDS must be between 1 and 86400")
        for name, value in (
            ("RATE_LIMIT_LLM_REQUESTS", self.rate_limit_llm_requests),
            ("RATE_LIMIT_DOCUMENT_UPLOADS", self.rate_limit_document_uploads),
            ("RATE_LIMIT_EMBEDDING_JOBS", self.rate_limit_embedding_jobs),
        ):
            if not 0 <= value <= 1_000_000:
                raise ValueError(f"{name} must be between 0 (unlimited) and 1000000")
        if not 1_000 <= self.rate_limit_max_tracked_keys <= 10_000_000:
            raise ValueError("RATE_LIMIT_MAX_TRACKED_KEYS must be between 1000 and 10000000")
        return self

    @model_validator(mode="after")
    def _validate_request_body_limit(self) -> Self:
        if not 1_024 <= self.max_request_body_bytes <= 256 * 1024 * 1024:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be between 1024 and 268435456")
        return self

    @model_validator(mode="after")
    def _validate_llm_stream_deadline(self) -> Self:
        if not 1 <= self.llm_stream_total_timeout_seconds <= 3600:
            raise ValueError("LLM_STREAM_TOTAL_TIMEOUT_SECONDS must be between 1 and 3600")
        return self

    @model_validator(mode="after")
    def _validate_a2a_limits(self) -> Self:
        if not 1_024 <= self.a2a_max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("A2A_MAX_RESPONSE_BYTES must be between 1024 and 67108864")
        if not 0 < self.a2a_total_timeout_seconds <= 600:
            raise ValueError("A2A_TOTAL_TIMEOUT_SECONDS must be greater than 0 and at most 600")
        return self

    @model_validator(mode="after")
    def _validate_document_limits(self) -> Self:
        for name, value, low, high in (
            ("DOCUMENT_MAX_UNCOMPRESSED_BYTES", self.document_max_uncompressed_bytes, 1_024, 2**32),
            ("DOCUMENT_MAX_PDF_PAGES", self.document_max_pdf_pages, 1, 100_000),
            ("DOCUMENT_MAX_EXTRACTED_CHARS", self.document_max_extracted_chars, 1_000, 10**9),
        ):
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        return self

    @model_validator(mode="after")
    def _validate_chat_history(self) -> Self:
        if not 1 <= self.chat_history_max_messages <= 500:
            raise ValueError("CHAT_HISTORY_MAX_MESSAGES must be between 1 and 500")
        if not 1_000 <= self.chat_history_max_chars <= 500_000:
            raise ValueError("CHAT_HISTORY_MAX_CHARS must be between 1000 and 500000")
        return self

    @model_validator(mode="after")
    def _validate_agent_memory(self) -> Self:
        for name, value, low, high in (
            ("AGENT_MEMORY_MAX_ITEM_CHARS", self.agent_memory_max_item_chars, 20, 2_000),
            ("AGENT_MEMORY_MAX_ITEMS_PER_USER", self.agent_memory_max_items_per_user, 1, 10_000),
            ("AGENT_MEMORY_MAX_WRITES_PER_RUN", self.agent_memory_max_writes_per_run, 0, 20),
            ("AGENT_MEMORY_MAX_RECALLED", self.agent_memory_max_recalled, 1, 50),
            ("AGENT_MEMORY_MAX_PROMPT_CHARS", self.agent_memory_max_prompt_chars, 100, 20_000),
            ("AGENT_MEMORY_TTL_DAYS", self.agent_memory_ttl_days, 1, 3_650),
        ):
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        return self

    @model_validator(mode="after")
    def _validate_metrics_token(self) -> Self:
        # Presence is enforced when serving; a token that IS set must not be trivially guessable.
        token = self.metrics_token.get_secret_value() if self.metrics_token else ""
        if token and token != token.strip():
            # A trailing newline from `kubectl create secret --from-file` or `echo` never matches
            # what a scraper sends, so /metrics would 401 forever with no hint why.
            raise ValueError("METRICS_TOKEN must not have leading or trailing whitespace")
        if token and len(token) < MIN_METRICS_TOKEN_CHARS:
            raise ValueError(f"METRICS_TOKEN must be at least {MIN_METRICS_TOKEN_CHARS} characters")
        return self

    @property
    def metrics_token_configured(self) -> bool:
        return self.metrics_token is not None and bool(self.metrics_token.get_secret_value())

    @property
    def auth_configured(self) -> bool:
        return bool(self.auth_issuer and self.auth_audience and self.auth_jwks_url)

    @property
    def sql_echo(self) -> bool:
        """SQL statement logging (with bound parameters, which include identity
        data) is only ever enabled in local development, whatever DEBUG says."""
        return self.debug and self.environment == "local"

    def validate_for_serving(self) -> None:
        """Refuses to let the API start outside local development without
        authentication configured. Called when the application is built;
        deliberately not part of settings loading (see the note in
        `_validate_auth_settings`). Also refuses an embedding dimension the schema cannot store."""
        # Imported here: the model module imports the database layer, which imports this module.
        from app.domain.models.chunk_embedding import EMBEDDING_DIMENSION

        if self.embedding_dimension != EMBEDDING_DIMENSION:
            raise ValueError(
                f"EMBEDDING_DIMENSION is {self.embedding_dimension} but the chunk_embeddings "
                f"vector column stores {EMBEDDING_DIMENSION}-dimensional vectors. Every chunk "
                "write and every retrieval would fail. Changing the dimension needs a new "
                "migration (a new column or table), not just a new setting."
            )
        if self.environment != "local" and "*" in self.cors_origins:
            # The API allows credentials on cross-origin requests, and Starlette answers a "*"
            # list with the caller's own origin, so "*" would let ANY site make credentialed
            # calls. Outside local development the origins must be listed explicitly.
            raise ValueError(
                "CORS_ORIGINS contains '*': list the frontend origins explicitly outside local "
                "development (credentials are allowed on cross-origin requests)."
            )
        if (
            self.metrics_enabled
            and not self.metrics_token_configured
            and (self.environment != "local")
        ):
            raise ValueError(
                "METRICS_ENABLED is true but METRICS_TOKEN is not set: /metrics requires a "
                f"bearer token outside local development (at least {MIN_METRICS_TOKEN_CHARS} "
                "characters). The API refuses to start without it."
            )
        # In local development an enabled endpoint without a token is mounted but answers 401
        # to everyone (it fails closed; app.main logs this once).
        if self.environment == "local" or self.auth_configured:
            return
        missing = [
            name
            for name, value in (
                ("AUTH_ISSUER", self.auth_issuer),
                ("AUTH_AUDIENCE", self.auth_audience),
                ("AUTH_JWKS_URL", self.auth_jwks_url),
            )
            if not value
        ]
        raise ValueError(
            f"Authentication is not configured for ENVIRONMENT={self.environment!r}: "
            f"set {', '.join(missing)}. The API refuses to start without it outside "
            "local development."
        )

    @property
    def has_groq_api_key(self) -> bool:
        """True only for an actually-usable key. `groq_api_key is not None`
        is not enough: a `.env` with `GROQ_API_KEY=""` (exactly what
        .env.example ships with) parses as `SecretStr('')`, not `None` —
        truthy as a plain `bool(...)` check since `SecretStr` doesn't
        override `__bool__`, which previously made `/api/v1/system/status`
        report `llm_configured: true` for a blank key."""
        return bool(self.groq_api_key) and bool(self.groq_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
