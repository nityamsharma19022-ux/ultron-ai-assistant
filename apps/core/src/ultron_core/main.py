"""ULTRON Core application factory.

Run locally:  uvicorn ultron_core.main:create_app --factory
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from ultron_core import __version__
from ultron_core.api import health
from ultron_core.auth import router as auth_router
from ultron_core.config import Settings, get_settings
from ultron_core.db.migrate import head_revision
from ultron_core.db.session import create_engine, create_sessionmaker
from ultron_core.logging_setup import configure_logging, get_logger
from ultron_core.middleware import RequestContextMiddleware
from ultron_core.redis_client import create_redis

log = get_logger("ultron.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = create_redis(settings)
    app.state.http = httpx.AsyncClient()
    app.state.schema_head = head_revision()
    log.info(
        "app.startup",
        version=__version__,
        env=settings.env,
        deployment=settings.deployment,
        node_id=settings.node_id,
        db_mode=settings.db_mode,
        schema_head=app.state.schema_head,
    )
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.redis.aclose()
        await engine.dispose()
        log.info("app.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    is_prod = settings.env == "production"
    app = FastAPI(
        title="ULTRON Core",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(auth_router.router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {"service": settings.service_name, "version": __version__, "health": "/health/live"}

    return app
