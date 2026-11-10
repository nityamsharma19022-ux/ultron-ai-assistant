"""Provider speed ranking: cloud providers are tried fastest first, by the
rolling average time to first word of their recent replies (measured by
Core for every reply). Providers without measurements keep their configured
place ahead of measured ones, so each gets measured once. Per-kind
preferences (ULTRON_AI_TASK_PROFILES) stay first."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.db.models import Conversation, Message

WINDOW = 20  # last replies per provider
MAX_AGE = timedelta(days=14)
CACHE_SECONDS = 30.0

_cache: dict[uuid.UUID, tuple[float, dict[str, float]]] = {}


async def averages(session: AsyncSession, user_id: uuid.UUID) -> dict[str, float]:
    """Average first-word time (ms) per cloud provider over its recent replies."""
    hit = _cache.get(user_id)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    recent = (
        select(
            Message.provider.label("provider"),
            Message.first_token_ms.label("ms"),
            func.row_number()
            .over(partition_by=Message.provider, order_by=Message.seq.desc())
            .label("n"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.user_id == user_id,
            Message.role == "assistant",
            Message.status == "complete",
            Message.provider_kind == "cloud",
            Message.first_token_ms.is_not(None),
            Message.created_at >= datetime.now(UTC) - MAX_AGE,
        )
        .subquery()
    )
    rows = await session.execute(
        select(recent.c.provider, func.avg(recent.c.ms))
        .where(recent.c.n <= WINDOW)
        .group_by(recent.c.provider)
    )
    result = {p: float(ms) for p, ms in rows.all()}
    _cache[user_id] = (now, result)
    return result


def forget(user_id: uuid.UUID | None = None) -> None:
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


def rank(order: Sequence[str], preferred: Sequence[str], avg: dict[str, float]) -> tuple[str, ...]:
    """preferred (as given) + unmeasured (configured order) + measured (fastest first)."""
    head = [p for p in preferred if p in order or p in avg]
    rest = [p for p in order if p not in head]
    unmeasured = [p for p in rest if p not in avg]
    measured = sorted((p for p in rest if p in avg), key=lambda p: avg[p])
    return (*head, *unmeasured, *measured)
