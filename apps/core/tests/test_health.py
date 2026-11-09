"""Health endpoints against the real local PostgreSQL and Redis."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

from tests.conftest import make_test_settings
from ultron_core.main import create_app

pytestmark = pytest.mark.integration


async def _get(settings, path: str) -> httpx.Response:  # type: ignore[no-untyped-def]
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.get(path)


async def test_live_identifies_the_backend(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "ultron-core"
    assert body["deployment"] == "local"
    assert body["node_id"] == "ultron-test-node"
    assert body["api_version"] == "v1"


async def test_ready_when_database_and_redis_are_up(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["db_mode"] == "local"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["database"]["schema"] == "up_to_date"
    assert body["checks"]["redis"]["status"] == "ok"
    assert body["checks"]["local_ai"] == {"status": "not_configured", "required": False}


async def test_not_ready_when_database_down_and_no_switch(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(
        local_database_url="postgresql://ultron:x@127.0.0.1:1/ultron_test",
        db_connect_timeout_seconds=1,
    )
    resp = await _get(settings, "/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["database"]["status"] == "error"
    # Still the configured database: nothing switched to another one.
    assert body["db_mode"] == "local"
    assert body["checks"]["redis"]["status"] == "ok"


async def test_not_ready_when_redis_down(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(redis_url="redis://127.0.0.1:1/0", redis_timeout_seconds=1)
    resp = await _get(settings, "/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"]["status"] == "error"
    assert resp.json()["checks"]["database"]["status"] == "ok"


async def test_local_ai_is_optional(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(ollama_base_url="http://127.0.0.1:1", ollama_model="llama3.2")
    resp = await _get(settings, "/health/ready")
    assert resp.status_code == 200
    local_ai = resp.json()["checks"]["local_ai"]
    assert local_ai["status"] == "unavailable"
    assert "not running" in local_ai["reason"]


async def test_liveness_survives_dependency_outage(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(
        local_database_url="postgresql://ultron:x@127.0.0.1:1/ultron_test",
        redis_url="redis://127.0.0.1:1/0",
    )
    resp = await _get(settings, "/health/live")
    assert resp.status_code == 200


async def test_request_id_is_returned(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health/live", headers={"X-Request-ID": "client-req-1"})
    assert resp.headers["x-request-id"] == "client-req-1"

    generated = await client.get("/health/live")
    assert len(generated.headers["x-request-id"]) == 32

    unsafe = await client.get("/health/live", headers={"X-Request-ID": "bad id\nwith newline"})
    assert unsafe.headers["x-request-id"] != "bad id\nwith newline"
