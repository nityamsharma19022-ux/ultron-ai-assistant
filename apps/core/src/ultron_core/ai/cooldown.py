"""Provider cooldowns: after a rate limit, quota exhaustion or outage the
router skips that provider for a while instead of hammering it.

Stored in Redis (shared by all workers) with an in-process copy so routing
keeps working if Redis is down.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ultron_core.config import Settings
from ultron_core.logging_setup import get_logger
from ultron_core.redis_client import redis_key

log = get_logger("ultron.ai.cooldown")

MAX_COOLDOWN_SECONDS = 6 * 3600


@dataclass(frozen=True, slots=True)
class Cooldown:
    code: str
    until: float  # unix time

    @property
    def remaining(self) -> float:
        return max(0.0, self.until - time.time())


class CooldownStore:
    def __init__(self, redis: Redis | None, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings
        self._memory: dict[str, Cooldown] = {}

    def _key(self, provider: str) -> str:
        return redis_key(self._settings, "ai", "cooldown", provider)

    async def set(self, provider: str, code: str, seconds: float) -> None:
        seconds = min(max(seconds, 1.0), MAX_COOLDOWN_SECONDS)
        cooldown = Cooldown(code=code, until=time.time() + seconds)
        self._memory[provider] = cooldown
        log.info("ai.cooldown_set", provider=provider, reason=code, seconds=round(seconds))
        if self._redis is None:
            return
        try:
            await self._redis.set(
                self._key(provider),
                json.dumps({"code": code, "until": cooldown.until}),
                ex=max(1, int(seconds)),
            )
        except RedisError as exc:
            log.warning("ai.cooldown_store_unavailable", error=type(exc).__name__)

    async def get(self, provider: str) -> Cooldown | None:
        cooldown: Cooldown | None = None
        if self._redis is not None:
            try:
                raw = await self._redis.get(self._key(provider))
                if raw:
                    data = json.loads(raw)
                    cooldown = Cooldown(code=data["code"], until=float(data["until"]))
            except (RedisError, ValueError, KeyError) as exc:
                log.warning("ai.cooldown_store_unavailable", error=type(exc).__name__)
                cooldown = self._memory.get(provider)
        else:
            cooldown = self._memory.get(provider)
        if cooldown is None or cooldown.remaining <= 0:
            return None
        return cooldown

    async def clear(self, provider: str) -> None:
        self._memory.pop(provider, None)
        if self._redis is not None:
            try:
                await self._redis.delete(self._key(provider))
            except RedisError:
                pass
