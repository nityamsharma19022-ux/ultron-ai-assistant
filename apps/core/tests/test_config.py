"""Configuration rules: separate local/cloud databases, no automatic fallback."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ultron_core.config import Settings, normalize_postgres_url

SECRET = "s" * 40
LOCAL = "postgresql://u:p@localhost:5433/ultron"
CLOUD = "postgresql://u:p@db.example-ultron.test:5432/postgres"


def make(**kw: object) -> Settings:
    kw.setdefault("jwt_secret", SECRET)
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("ULTRON_"):
            monkeypatch.delenv(key)


def test_local_mode_uses_local_url() -> None:
    s = make(db_mode="local", local_database_url=LOCAL, cloud_database_url=CLOUD)
    assert s.database_url == "postgresql+asyncpg://u:p@localhost:5433/ultron"


def test_cloud_mode_uses_cloud_url() -> None:
    s = make(db_mode="cloud", local_database_url=LOCAL, cloud_database_url=CLOUD)
    assert "example-ultron.test" in s.database_url


def test_cloud_mode_without_cloud_url_never_falls_back_to_local() -> None:
    with pytest.raises(ValidationError, match="never falls back"):
        make(db_mode="cloud", local_database_url=LOCAL)


def test_local_mode_without_local_url_never_falls_back_to_cloud() -> None:
    with pytest.raises(ValidationError, match="ULTRON_LOCAL_DATABASE_URL"):
        make(db_mode="local", cloud_database_url=CLOUD)


def test_only_ultron_prefixed_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # Generic names other projects commonly use must be ignored.
    monkeypatch.setenv("DATABASE_URL", "postgresql://other:other@other-project/other")
    monkeypatch.setenv("JWT_SECRET", "z" * 40)
    monkeypatch.setenv("ULTRON_LOCAL_DATABASE_URL", LOCAL)
    monkeypatch.setenv("ULTRON_JWT_SECRET", SECRET)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "other-project" not in s.database_url
    assert s.jwt_secret.get_secret_value() == SECRET


def test_url_normalisation() -> None:
    assert normalize_postgres_url("postgres://a@h/d") == "postgresql+asyncpg://a@h/d"
    with pytest.raises(ValueError):
        normalize_postgres_url("mysql://a@h/d")


def test_short_jwt_secret_rejected() -> None:
    with pytest.raises(ValidationError, match="32 characters"):
        make(local_database_url=LOCAL, jwt_secret="short")


def test_placeholder_secret_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        make(
            env="production",
            local_database_url=LOCAL,
            jwt_secret="change-me-replace-with-a-long-random-string",
        )


def test_redis_prefix_must_stay_in_ultron_namespace() -> None:
    with pytest.raises(ValidationError, match="ultron"):
        make(local_database_url=LOCAL, redis_key_prefix="app:")


def test_secrets_are_not_exposed_in_repr() -> None:
    s = make(local_database_url=LOCAL)
    assert SECRET not in repr(s)
    assert "u:p@" not in repr(s)


def test_env_example_loads_and_enables_no_cloud_provider_by_default() -> None:
    from pathlib import Path

    import httpx

    from ultron_core.ai.registry import build_providers

    example = Path(__file__).resolve().parents[3] / ".env.example"
    s = Settings(_env_file=example)  # type: ignore[call-arg]
    assert s.db_mode == "local"
    assert s.ai_dev_mock == "off"
    providers = build_providers(s, httpx.AsyncClient())
    # No keys in the template: no cloud provider (free or paid) is active.
    assert [p.name for p in providers if p.is_configured() and p.kind.value == "cloud"] == []
    # Local AI is pre-set for the owner's Windows setup (Ollama + qwen3.5:4b).
    local = next(p for p in providers if p.name == "ollama")
    assert local.model == "qwen3.5:4b"
    assert s.ollama_base_url == "http://127.0.0.1:11434"
    assert s.ollama_allow_remote is False
    assert (s.ai_max_reply_seconds, s.ai_stream_keepalive_seconds) == (300, 10)
    assert (s.ollama_think, s.ollama_num_ctx) == ("false", 8192)
