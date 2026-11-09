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

    # --- Optional local AI (reported in readiness, used from Phase 2) ----
    ollama_base_url: str | None = None

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
        if not self.redis_key_prefix.startswith("ultron"):
            raise ValueError(
                "ULTRON_REDIS_KEY_PREFIX must start with 'ultron' to keep keys isolated."
            )
        return self

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
