"""ULTRON Core application factory.

Run locally:  uvicorn ultron_core.main:create_app --factory
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from ultron_core import __version__, activity, backup, modes, notifications, pairing, voice
from ultron_core.ai import api as ai_api
from ultron_core.ai.cooldown import CooldownStore
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.registry import build_providers, build_router
from ultron_core.api import health
from ultron_core.auth import router as auth_router
from ultron_core.chat import router as chat_router
from ultron_core.chat.generation import GenerationManager
from ultron_core.chat.service import mark_stale_generations_failed
from ultron_core.config import Settings, get_settings
from ultron_core.db.migrate import head_revision
from ultron_core.db.session import create_engine, create_sessionmaker
from ultron_core.documents import router as documents_router
from ultron_core.logging_setup import configure_logging, get_logger
from ultron_core.memory import router as memory_router
from ultron_core.middleware import RequestContextMiddleware
from ultron_core.redis_client import create_redis
from ultron_core.tasks import agents as agents_router
from ultron_core.tasks import router as tasks_router
from ultron_core.tasks.engine import TaskEngine

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
    providers: list[ChatProvider] = app.state.provider_override or build_providers(
        settings, app.state.http
    )
    app.state.ai_router = build_router(
        settings, providers, CooldownStore(app.state.redis, settings)
    )
    app.state.generations = GenerationManager()
    app.state.task_engine = TaskEngine(app.state.sessionmaker, app.state.ai_router, settings)
    app.state.task_engine.redis = app.state.redis
    app.state.task_engine.http = app.state.http
    try:
        async with app.state.sessionmaker() as session:
            stale = await mark_stale_generations_failed(session)
        if stale:
            log.warning("chat.stale_replies_marked_failed", count=stale)
    except Exception as exc:
        log.warning("chat.stale_check_skipped", error=type(exc).__name__)
    log.info(
        "app.startup",
        version=__version__,
        env=settings.env,
        deployment=settings.deployment,
        node_id=settings.node_id,
        db_mode=settings.db_mode,
        schema_head=app.state.schema_head,
        ai_providers=[f"{p.name}({p.kind.value})" for p in providers if p.is_configured()],
    )
    if app.state.start_task_engine:
        app.state.task_engine.start()
    try:
        yield
    finally:
        await app.state.task_engine.stop()
        await app.state.generations.shutdown()
        for provider in providers:
            await provider.aclose()
        await app.state.http.aclose()
        await app.state.redis.aclose()
        await engine.dispose()
        log.info("app.shutdown")


def create_app(
    settings: Settings | None = None,
    *,
    ai_providers: list[ChatProvider] | None = None,
    start_task_engine: bool = True,
    transcriber: voice.Transcriber | None = None,
) -> FastAPI:
    """``ai_providers`` replaces the configured providers and
    ``start_task_engine=False`` leaves the background task loop off (tests
    drive it step by step)."""
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
    app.state.provider_override = ai_providers
    app.state.start_task_engine = start_task_engine
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(chat_router.router, prefix="/api/v1")
    app.include_router(ai_api.router, prefix="/api/v1")
    app.include_router(memory_router.router, prefix="/api/v1")
    app.include_router(documents_router.router, prefix="/api/v1")
    app.include_router(pairing.router, prefix="/api/v1")
    app.include_router(modes.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(backup.router, prefix="/api/v1")
    app.include_router(voice.router, prefix="/api/v1")
    # Speech-to-text: tests pass a fake; otherwise faster-whisper if installed.
    if transcriber is None and settings.stt_enabled and voice.whisper_available():
        transcriber = voice.WhisperTranscriber(settings)
    app.state.transcriber = transcriber
    app.state.transcribe_lock = asyncio.Lock()
    app.include_router(activity.router, prefix="/api/v1")
    app.include_router(tasks_router.router, prefix="/api/v1")
    app.include_router(agents_router.router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {"service": settings.service_name, "version": __version__, "health": "/health/live"}

    return app
