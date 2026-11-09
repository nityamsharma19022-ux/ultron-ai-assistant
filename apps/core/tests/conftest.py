"""Shared fixtures.

Unit tests need nothing running. Integration tests (marked
``integration``) use the local ULTRON PostgreSQL and Redis from
``docker compose up -d postgres redis``:

- a dedicated ``ultron_test`` database, recreated once per test session;
- Redis keys under the ``ultron-test:`` prefix, deleted after each test.

Override with ULTRON_TEST_DATABASE_URL / ULTRON_TEST_REDIS_URL (used in CI).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url

from ultron_core.config import Settings
from ultron_core.db import migrate
from ultron_core.main import create_app

TEST_DB_NAME = "ultron_test"
TEST_REDIS_PREFIX = "ultron-test:"
TEST_JWT_SECRET = "test-only-jwt-secret-" + "x" * 32
OWNER_EMAIL = "owner@ultron.test"
OWNER_PASSWORD = "correct-horse-battery-staple"


def _derive_test_urls() -> tuple[str, str]:
    db_url = os.environ.get("ULTRON_TEST_DATABASE_URL")
    redis_url = os.environ.get("ULTRON_TEST_REDIS_URL")
    if db_url and redis_url:
        return db_url, redis_url

    # Derive from the developer's ULTRON .env (local database only).
    base = Settings(db_mode="local", jwt_secret=TEST_JWT_SECRET)
    if not db_url:
        assert base.local_database_url is not None
        db_url = (
            make_url(base.local_database_url.get_secret_value())
            .set(database=TEST_DB_NAME)
            .render_as_string(hide_password=False)
        )
    if not redis_url:
        parts = urlsplit(base.redis_url.get_secret_value())
        redis_url = urlunsplit(parts._replace(path="/15"))
    return db_url, redis_url


def make_test_settings(**overrides: object) -> Settings:
    db_url, redis_url = _derive_test_urls()
    values: dict[str, object] = {
        "env": "test",
        "deployment": "local",
        "node_id": "ultron-test-node",
        "db_mode": "local",
        "local_database_url": db_url,
        "cloud_database_url": None,
        "redis_url": redis_url,
        "redis_key_prefix": TEST_REDIS_PREFIX,
        "jwt_secret": TEST_JWT_SECRET,
        "ollama_base_url": None,
        "login_rate_limit_attempts": 5,
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return make_test_settings()


async def _recreate_database(settings: Settings) -> None:
    url = make_url(settings.database_url)
    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_database(test_settings: Settings) -> Settings:
    """Fresh ultron_test database at the latest migration (once per session)."""
    assert make_url(test_settings.database_url).database == TEST_DB_NAME
    asyncio.run(_recreate_database(test_settings))
    migrate.upgrade(test_settings)
    return test_settings


async def _reset_state(app: FastAPI) -> None:
    async with app.state.engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, devices, refresh_tokens CASCADE"))
    keys = [k async for k in app.state.redis.scan_iter(match=f"{TEST_REDIS_PREFIX}*")]
    if keys:
        await app.state.redis.delete(*keys)


@pytest.fixture
async def app(migrated_database: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(migrated_database)
    async with LifespanManager(application):
        await _reset_state(application)
        yield application
        await _reset_state(application)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ultron.test") as c:
        yield c


@pytest.fixture
async def owner(app: FastAPI):  # type: ignore[no-untyped-def]
    from ultron_core.auth.service import create_owner

    async with app.state.sessionmaker() as session:
        return await create_owner(session, OWNER_EMAIL, OWNER_PASSWORD, "Owner")


async def login(
    client: httpx.AsyncClient,
    *,
    email: str = OWNER_EMAIL,
    password: str = OWNER_PASSWORD,
    device_name: str = "Pixel",
    platform: str = "android",
    device_id: str | None = None,
) -> httpx.Response:
    body: dict[str, object] = {
        "email": email,
        "password": password,
        "device_name": device_name,
        "platform": platform,
    }
    if device_id:
        body["device_id"] = device_id
    return await client.post("/api/v1/auth/login", json=body)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
