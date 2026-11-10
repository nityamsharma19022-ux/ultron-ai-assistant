"""Proactive rules: what ULTRON tells you without being asked.

Run by the task engine about every half minute. Each rule writes a
notification with a dedupe key, so the same situation is reported once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.config import Settings
from ultron_core.db.models import (
    AgentInfo,
    Device,
    NotificationSettings,
    Reminder,
    Task,
    TaskStep,
    User,
)
from ultron_core.notifications import get_settings, notify, read_metrics

APPROVAL_NUDGE = timedelta(minutes=5)
OFFLINE_NUDGE = timedelta(minutes=10)
PAUSED_NUDGE = timedelta(days=1)
LOW_BATTERY = 15


def now() -> datetime:
    return datetime.now(UTC)


async def run(session: AsyncSession, redis: Redis, settings: Settings) -> int:
    """Applies every rule for every user; returns notifications created."""
    created = 0
    users = list(await session.scalars(select(User).where(User.is_active.is_(True))))
    for user in users:
        created += await _for_user(session, redis, settings, user)
    await session.commit()
    return created


async def _for_user(session: AsyncSession, redis: Redis, settings: Settings, user: User) -> int:
    n = 0
    t = now()
    # Approvals waiting a while.
    waiting = await session.scalars(
        select(Task).where(
            Task.user_id == user.id,
            Task.status == "awaiting_approval",
            Task.updated_at < t - APPROVAL_NUDGE,
        )
    )
    for task in waiting:
        n += await notify(
            session,
            user.id,
            "task.approval",
            f"Waiting for your approval: {task.title}",
            "Open Tasks to approve or reject it.",
            priority="normal",
            task_id=task.id,
            dedupe_key=f"approval:{task.id}",
        )
    # Due reminders.
    due = await session.scalars(
        select(Reminder).where(
            Reminder.user_id == user.id, Reminder.done.is_(False), Reminder.due_at <= t
        )
    )
    for r in due:
        n += await notify(
            session,
            user.id,
            "reminder",
            f"Reminder: {r.text}",
            priority="high",
            task_id=r.task_id,
            dedupe_key=f"reminder:{r.id}",
        )
    # Steps waiting for a device that isn't connected.
    ready = (
        await session.execute(
            select(TaskStep.target, func.count())
            .join(Task, Task.id == TaskStep.task_id)
            .where(
                Task.user_id == user.id,
                TaskStep.status == "ready",
                TaskStep.started_at < t - OFFLINE_NUDGE,
            )
            .group_by(TaskStep.target)
        )
    ).all()
    for target, count in ready:
        online = await session.scalar(
            select(func.count())
            .select_from(AgentInfo)
            .where(
                AgentInfo.user_id == user.id,
                AgentInfo.target == target,
                AgentInfo.last_seen_at > t - timedelta(seconds=90),
            )
        )
        if not online:
            name = "PC" if target == "windows" else "phone"
            n += await notify(
                session,
                user.id,
                "device.offline",
                f"Your {name} isn't connected",
                f"{count} step(s) are waiting for it. Start the ULTRON agent / open the app.",
                priority="high",
                dedupe_key=f"offline:{target}:{t:%Y-%m-%d}",
            )
    # Paused for a long time.
    paused = await session.scalars(
        select(Task).where(
            Task.user_id == user.id, Task.status == "paused", Task.updated_at < t - PAUSED_NUDGE
        )
    )
    for task in paused:
        n += await notify(
            session,
            user.id,
            "task.paused",
            f"Still paused: {task.title}",
            "Resume or cancel it in Tasks.",
            priority="low",
            task_id=task.id,
            dedupe_key=f"paused:{task.id}",
        )
    # Low battery on any device.
    devices = await session.scalars(
        select(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))
    )
    for d in devices:
        m = await read_metrics(redis, settings, d.id)
        if m and m.get("battery_percent") is not None and not m.get("charging"):
            if m["battery_percent"] <= LOW_BATTERY:
                n += await notify(
                    session,
                    user.id,
                    "device.battery",
                    f"{d.name} battery is low",
                    f"{m['battery_percent']:.0f}% and not charging.",
                    priority="normal",
                    dedupe_key=f"battery:{d.id}:{t:%Y-%m-%d}",
                )
    n += await _briefing(session, user, await get_settings(session, user.id))
    return n


async def _briefing(session: AsyncSession, user: User, s: NotificationSettings) -> int:
    if not s.daily_briefing:
        return 0
    local = now().astimezone(timezone(timedelta(minutes=s.utc_offset_minutes)))
    today = local.date().isoformat()
    if s.last_briefing_on == today or local.strftime("%H:%M") < s.daily_briefing:
        return 0
    s.last_briefing_on = today
    waiting = (
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.user_id == user.id, Task.status.in_(("awaiting_approval", "queued", "paused"))
            )
        )
        or 0
    )
    failed = (
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.user_id == user.id,
                Task.status == "failed",
                Task.finished_at > now() - timedelta(days=1),
            )
        )
        or 0
    )
    end_of_day = now() + timedelta(hours=24 - local.hour)
    reminders = (
        await session.scalar(
            select(func.count())
            .select_from(Reminder)
            .where(
                Reminder.user_id == user.id,
                Reminder.done.is_(False),
                Reminder.due_at <= end_of_day,
            )
        )
        or 0
    )
    parts = [f"{waiting} task(s) waiting", f"{reminders} reminder(s) today"]
    if failed:
        parts.append(f"{failed} task(s) failed in the last day")
    return await notify(
        session,
        user.id,
        "briefing",
        "Your daily briefing",
        ", ".join(parts) + ".",
        priority="normal",
        dedupe_key=f"briefing:{today}",
    )
