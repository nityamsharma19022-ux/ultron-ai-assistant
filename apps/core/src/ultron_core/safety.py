"""Automatic safety pause.

If automation suddenly behaves unusually (many tasks failing, or a flood of
new tasks in a short time, e.g. a script or a compromised device sending
commands), ULTRON turns the automation master switch off, records why and
sends an urgent notification. Only the owner turns it back on (Tasks →
Permissions). Nothing is deleted or undone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core import activity
from ultron_core.db.models import Task
from ultron_core.tasks.permissions import automation_state

FAILURE_LIMIT = 6
FAILURE_WINDOW = timedelta(minutes=15)
CREATION_LIMIT = 60
CREATION_WINDOW = timedelta(minutes=10)


async def _pause(session: AsyncSession, user_id: uuid.UUID, reason: str) -> bool:
    from ultron_core.notifications import notify

    state = await automation_state(session, user_id)
    if not state.enabled:
        return False
    state.enabled = False
    activity.record(
        session, user_id, "automation.auto_paused", f"Automation paused for safety: {reason}"
    )
    await notify(
        session,
        user_id,
        "automation.paused",
        "Automation paused for safety",
        f"{reason}. Check Tasks → Activity, then turn automation back on if all is well.",
        priority="urgent",
        dedupe_key=f"auto-paused:{datetime.now(UTC):%Y%m%d%H%M}",
    )
    return True


async def after_failure(session: AsyncSession, user_id: uuid.UUID) -> bool:
    since = datetime.now(UTC) - FAILURE_WINDOW
    failed = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.user_id == user_id, Task.status == "failed", Task.finished_at >= since)
    )
    if (failed or 0) >= FAILURE_LIMIT:
        return await _pause(session, user_id, f"{failed} tasks failed in 15 minutes")
    return False


async def after_create(session: AsyncSession, user_id: uuid.UUID) -> bool:
    since = datetime.now(UTC) - CREATION_WINDOW
    created = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.user_id == user_id, Task.created_at >= since)
    )
    if (created or 0) >= CREATION_LIMIT:
        return await _pause(session, user_id, f"{created} new tasks in 10 minutes")
    return False
