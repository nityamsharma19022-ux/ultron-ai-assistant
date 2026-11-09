"""ULTRON Core configuration.

All settings come from environment variables prefixed ``ULTRON_`` (or from
the repository's ``.env`` file). Nothing here is shared with any other
project.

Database rule: exactly one database is selected at startup via
``ULTRON_DB_MODE``. There is no automatic fallback between the local and
cloud databases; switching requires a deliberate config change plus a
defined synchronisation/migration step (see docs/SYNC.md).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/core/src/ultron_core/config.py -> repository root is 4 levels up.
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parents[3]

# Later files override earlier ones; real environment variables override both.
_ENV_FILES = (_REPO_ROOT / ".env", Path.cwd() / ".env")

_INSECURE_SECRET_MARKERS = ("change-me", "changeme", "example", "secret")

ASYNC_PG_SCHEME = "postgresql+asyncpg://"


def normalize_postgres_url(url: str) -> str:
    """Return ``url`` using SQLAlchemy's asyncpg driver scheme."""
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return ASYNC_PG_SCHEME + url[len(prefix) :]
    raise ValueError("Database URL must start with postgresql:// or postgres://")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ULTRON_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -------------------------------------------------------
    env: Literal["development", "test", "production"] = "development"
    # Where this backend instance runs. Clients use it to tell the cloud
    # backend from the Windows local backend.
    deployment: Literal["local", "cloud"] = "local"
    # Stable identifier for this backend instance (shown in health checks).
    node_id: str = "ultron-local"
    service_name: str = "ultron-core"

    # --- Logging -------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # --- Database (local and cloud kept separate) -----------------------
    db_mode: Literal["local", "cloud"] = "local"
    local_database_url: SecretStr | None = None
    cloud_database_url: SecretStr | None = None
    # Safety catch: migrations against the cloud database must be explicit.
    allow_cloud_migrations: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: float = Field(default=5.0, gt=0)

    # --- Redis ---------------------------------------------------------
    redis_url: SecretStr = SecretStr("redis://localhost:6380/0")
    redis_key_prefix: str = "ultron:"
    redis_timeout_seconds: float = Field(default=3.0, gt=0)

    # --- Authentication --------------------------------------------------
    jwt_secret: SecretStr
    jwt_issuer: str = "ultron-core"
    jwt_audience: str = "ultron-clients"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    login_rate_limit_attempts: int = Field(default=10, ge=1)
    login_rate_limit_window_seconds: int = Field(default=300, ge=10)

    # --- AI routing (cloud-first, local-fallback) -------------------------
    # Default order in which cloud providers are tried. Providers without an
    # API key + model are skipped automatically.
    ai_cloud_providers: str = "groq,gemini,openrouter,custom,anthropic"
    ai_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    ai_request_timeout_seconds: float = Field(default=90.0, gt=0, le=600)
    ai_max_output_tokens: int = Field(default=2048, ge=64, le=32_000)
    ai_cloud_context_chars: int = Field(default=48_000, ge=2_000, le=2_000_000)
    ai_local_context_chars: int = Field(default=16_000, ge=2_000, le=500_000)
    ai_context_max_messages: int = Field(default=40, ge=2, le=500)
    # Development-only fake provider: "off", "cloud" or "local".
    ai_dev_mock: Literal["off", "cloud", "local"] = "off"
    # Hard cap on one reply (seconds), including model loading.
    ai_max_reply_seconds: float = Field(default=300.0, ge=1, le=3600)
    # Interval for SSE keep-alive comments while waiting (e.g. model loading).
    ai_stream_keepalive_seconds: float = Field(default=10.0, gt=0, le=120)

    # Cloud providers (all optional). Keys stay on the server, never sent to clients.
    groq_api_key: SecretStr | None = None
    groq_model: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    custom_ai_api_key: SecretStr | None = None
    custom_ai_model: str | None = None
    custom_ai_base_url: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = "claude-opus-5-5"
    anthropic_max_tokens: int = Field(default=16_000, ge=256, le=128_000)
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    anthropic_base_url: str | None = None

    # Local AI (Ollama). Optional; never assumed to exist.
    ollama_base_url: str | None = None
    ollama_model: str | None = "qwen3.5:4b"
    # Local AI is restricted to this machine. Set true only for a deliberately
    # secured remote Ollama reached over https (see docs/SECURITY.md).
    ollama_allow_remote: bool = False
    # Reasoning ("thinking") for models like Qwen 3.5: "false" (default:
    # fastest replies), "true", "low"/"medium"/"high", or "default" (model's
    # own default). Reasoning text is never shown to the user.
    ollama_think: Literal["false", "true", "low", "medium", "high", "default"] = "false"
    # Context window sent to Ollama (tokens). Ollama's own default can be 4096.
    ollama_num_ctx: int | None = Field(default=8192, ge=1024, le=1_048_576)
    # How long Ollama keeps the model loaded after a request, e.g. "10m".
    ollama_keep_alive: str | None = None

    # --- Chat ---------------------------------------------------------------
    chat_max_message_chars: int = Field(default=12_000, ge=100, le=100_000)
    chat_rate_limit_per_minute: int = Field(default=20, ge=1, le=1000)

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        selected = self.cloud_database_url if self.db_mode == "cloud" else self.local_database_url
        if selected is None or not selected.get_secret_value().strip():
            var = f"ULTRON_{self.db_mode.upper()}_DATABASE_URL"
            raise ValueError(
                f"ULTRON_DB_MODE={self.db_mode} but {var} is not set. "
                "ULTRON never falls back to another database automatically."
            )
        normalize_postgres_url(selected.get_secret_value())  # validates scheme

        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32:
            raise ValueError("ULTRON_JWT_SECRET must be at least 32 characters.")
        looks_placeholder = any(m in secret.lower() for m in _INSECURE_SECRET_MARKERS)
        if self.env == "production" and looks_placeholder:
            raise ValueError("ULTRON_JWT_SECRET looks like a placeholder; set a real secret.")
        if self.env == "production" and self.ai_dev_mock != "off":
            raise ValueError("ULTRON_AI_DEV_MOCK must be 'off' in production.")
        if not self.redis_key_prefix.startswith("ultron"):
            raise ValueError(
                "ULTRON_REDIS_KEY_PREFIX must start with 'ultron' to keep keys isolated."
            )
        return self

    @property
    def cloud_provider_order(self) -> list[str]:
        return [n.strip().lower() for n in self.ai_cloud_providers.split(",") if n.strip()]

    @property
    def private_conversations_allowed(self) -> bool:
        """Private chats are stored only by a local backend using a local database."""
        return self.deployment == "local" and self.db_mode == "local"

    @property
    def database_url(self) -> str:
        """The single active database URL (asyncpg scheme), chosen by db_mode."""
        selected = self.cloud_database_url if self.db_mode == "cloud" else self.local_database_url
        if selected is None:  # unreachable: enforced by _validate
            raise RuntimeError("No database URL configured")
        return normalize_postgres_url(selected.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
