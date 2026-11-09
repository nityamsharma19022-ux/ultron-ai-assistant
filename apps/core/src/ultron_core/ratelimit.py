"""Generic fixed-window rate limiter on Redis (fails open if Redis is down)."""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ultron_core.config import Settings
from ultron_core.logging_setup import get_logger
from ultron_core.redis_client import redis_key

log = get_logger("ultron.ratelimit")


async def allow(
    redis: Redis, settings: Settings, *, bucket: str, identity: str, limit: int, window: int
) -> bool:
    key = redis_key(settings, "ratelimit", bucket, identity)
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
            count, _ = await pipe.execute()
    except RedisError as exc:
        log.warning("ratelimit.unavailable", bucket=bucket, error=type(exc).__name__)
        return True
    return int(count) <= limit
