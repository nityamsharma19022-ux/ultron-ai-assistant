"""Health endpoints.

- ``/health/live``: the process is up. Never touches dependencies. Clients
  also use it to discover *which* backend they reached (cloud vs. the
  Windows local backend).
- ``/health/ready``: PostgreSQL (incl. schema version) and Redis are usable.
  Returns 503 when not ready. The optional local AI runtime is reported but
  never affects readiness.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from ultron_core import __version__
from ultron_core.deps import SettingsDep

router = APIRouter(prefix="/health", tags=["health"])

API_VERSION = "v1"


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


async def check_database(request: Request, limit_seconds: float) -> dict[str, Any]:
    start = time.perf_counter()
    expected = request.app.state.schema_head
    try:
        async with asyncio.timeout(limit_seconds):
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                has_table = await conn.scalar(text("SELECT to_regclass('alembic_version')"))
                current = (
                    await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
                    if has_table
                    else None
                )
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__, "latency_ms": _ms(start)}

    schema = "up_to_date" if current == expected else "outdated"
    return {
        "status": "ok" if schema == "up_to_date" else "error",
        "schema": schema,
        "revision": current,
        "expected_revision": expected,
        "latency_ms": _ms(start),
    }


async def check_redis(request: Request, limit_seconds: float) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        async with asyncio.timeout(limit_seconds):
            await request.app.state.redis.ping()
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__, "latency_ms": _ms(start)}
    return {"status": "ok", "latency_ms": _ms(start)}


async def check_local_ai(request: Request) -> dict[str, Any]:
    """Optional: reports whether a local model is really installed. Never
    affects readiness."""
    local = request.app.state.ai_router.local_providers
    configured = [p for p in local if p.is_configured()]
    if not configured:
        return {"status": "not_configured", "required": False}
    provider = configured[0]
    availability = await provider.availability()
    if not availability.available:
        return {
            "status": "unavailable",
            "required": False,
            "model": provider.model,
            "reason": availability.reason,
        }
    return {"status": "ok", "required": False, "model": provider.model}


@router.get("/live")
async def live(settings: SettingsDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": __version__,
        "api_version": API_VERSION,
        "deployment": settings.deployment,
        "node_id": settings.node_id,
        "time": datetime.now(UTC).isoformat(),
    }


@router.get("/ready")
async def ready(request: Request, response: Response, settings: SettingsDep) -> dict[str, Any]:
    db, redis, local_ai = await asyncio.gather(
        check_database(request, settings.db_connect_timeout_seconds),
        check_redis(request, settings.redis_timeout_seconds),
        check_local_ai(request),
    )
    is_ready = db["status"] == "ok" and redis["status"] == "ok"
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if is_ready else "not_ready",
        "deployment": settings.deployment,
        "node_id": settings.node_id,
        "db_mode": settings.db_mode,
        "checks": {"database": db, "redis": redis, "local_ai": local_ai},
    }
