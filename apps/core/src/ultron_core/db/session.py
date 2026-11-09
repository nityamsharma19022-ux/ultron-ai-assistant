"""Async SQLAlchemy engine/session factories for the single active database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ultron_core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    # Engines connect lazily: the app still starts (and reports "not ready")
    # if the database is down. It never switches to another database.
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "server_settings": {"application_name": settings.service_name},
        },
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
