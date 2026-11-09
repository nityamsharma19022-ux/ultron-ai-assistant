"""Redis client factory and ULTRON key namespacing."""

from __future__ import annotations

from redis.asyncio import Redis

from ultron_core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        health_check_interval=30,
    )


def redis_key(settings: Settings, *parts: str) -> str:
    """Build a namespaced key, e.g. ``ultron:ratelimit:login:1.2.3.4``."""
    return settings.redis_key_prefix + ":".join(parts)
