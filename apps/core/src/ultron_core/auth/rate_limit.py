"""Fixed-window login rate limiting backed by Redis.

Fails *open* if Redis is unavailable (logged as a warning) so the owner is
never locked out of a local-fallback backend just because Redis is down.
"""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ultron_core.config import Settings
from ultron_core.logging_setup import get_logger
from ultron_core.redis_client import redis_key

log = get_logger("ultron.auth.ratelimit")


def _email_key(email: str) -> str:
    # Hash so raw email addresses are never stored as Redis keys.
    return hashlib.sha256(email.lower().encode()).hexdigest()[:32]


class LoginRateLimiter:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    def _keys(self, client_ip: str, email: str) -> list[str]:
        return [
            redis_key(self.settings, "ratelimit", "login", "ip", client_ip),
            redis_key(self.settings, "ratelimit", "login", "email", _email_key(email)),
        ]

    async def register_attempt(self, client_ip: str, email: str) -> bool:
        """Count an attempt; return False if the caller is over the limit."""
        window = self.settings.login_rate_limit_window_seconds
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                for key in self._keys(client_ip, email):
                    pipe.incr(key)
                    pipe.expire(key, window, nx=True)
                results = await pipe.execute()
        except RedisError as exc:
            log.warning("ratelimit.unavailable", error=type(exc).__name__)
            return True
        counts = results[0::2]
        return max(counts) <= self.settings.login_rate_limit_attempts

    async def reset_email(self, email: str) -> None:
        try:
            await self.redis.delete(self._keys("-", email)[1])
        except RedisError as exc:
            log.warning("ratelimit.unavailable", error=type(exc).__name__)
