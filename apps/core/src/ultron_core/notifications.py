"""Notifications (/api/v1/notifications) and live device metrics
(/api/v1/devices/metrics).

ULTRON records what you should know (failed tasks, approvals waiting,
reminders, offline devices, low battery, a daily briefing). Every device
lists them; each item says whether to *announce* it now (pop up / speak),
which respects priority, quiet hours and quiet operating modes.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.db.models import Device, Notification, NotificationSettings
from ultron_core.deps import PrincipalDep, RedisDep, SessionDep, SettingsDep
from ultron_core.redis_client import redis_key

PRIORITIES = ("low", "normal", "high", "urgent")
Priority = Literal["low", "normal", "high", "urgent"]
METRICS_TTL = 180


def rank(priority: str) -> int:
    return PRIORITIES.index(priority) if priority in PRIORITIES else 1


async def notify(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str = "",
    *,
    priority: str = "normal",
    task_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Adds a notification (once per dedupe_key). Caller commits."""
    stmt = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind,
            title=title[:200],
            body=body[:1000],
            priority=priority,
            task_id=task_id,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
    )
    result = await session.execute(stmt)
    return bool(result.rowcount)


async def get_settings(session: AsyncSession, user_id: uuid.UUID) -> NotificationSettings:
    s = await session.get(NotificationSettings, user_id)
    if s is None:
        s = NotificationSettings(user_id=user_id, utc_offset_minutes=0, min_priority="normal")
        session.add(s)
        await session.flush()
    return s


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def in_quiet_hours(s: NotificationSettings, now: datetime | None = None) -> bool:
    if not s.quiet_start or not s.quiet_end:
        return False
    local = (now or datetime.now(UTC)).astimezone(timezone(timedelta(minutes=s.utc_offset_minutes)))
    t, start, end = local.time(), _hm(s.quiet_start), _hm(s.quiet_end)
    return start <= t < end if start <= end else (t >= start or t < end)


def should_announce(
    n: Notification, s: NotificationSettings, *, mode_quiet: bool, now: datetime | None = None
) -> bool:
    """Urgent always; nothing else in quiet hours; a quiet mode (Focus) lets
    only high priority through; otherwise the user's minimum priority."""
    if n.read_at is not None:
        return False
    if n.priority == "urgent":
        return True
    if in_quiet_hours(s, now):
        return False
    if mode_quiet:
        return rank(n.priority) >= rank("high")
    return rank(n.priority) >= rank(s.min_priority)


# --- API -----------------------------------------------------------------------

router = APIRouter(tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    priority: str
    task_id: uuid.UUID | None
    read: bool
    announce: bool
    created_at: datetime


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    quiet_start: str | None
    quiet_end: str | None
    utc_offset_minutes: int
    min_priority: str
    daily_briefing: str | None


HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quiet_start: str | None = Field(default=None, pattern=HHMM)
    quiet_end: str | None = Field(default=None, pattern=HHMM)
    utc_offset_minutes: int = Field(default=0, ge=-14 * 60, le=14 * 60)
    min_priority: Priority = "normal"
    daily_briefing: str | None = Field(default=None, pattern=HHMM)


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    principal: PrincipalDep,
    session: SessionDep,
    unread: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationOut]:
    from ultron_core.modes import active_mode

    s = await get_settings(session, principal.user.id)
    quiet = (await active_mode(session, principal.user)).quiet
    query = select(Notification).where(Notification.user_id == principal.user.id)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    rows = list(await session.scalars(query.order_by(Notification.created_at.desc()).limit(limit)))
    await session.commit()
    return [
        NotificationOut(
            id=n.id,
            kind=n.kind,
            title=n.title,
            body=n.body,
            priority=n.priority,
            task_id=n.task_id,
            read=n.read_at is not None,
            created_at=n.created_at,
            announce=should_announce(n, s, mode_quiet=quiet),
        )
        for n in rows
    ]


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != principal.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    n.read_at = n.read_at or datetime.now(UTC)
    await session.commit()


@router.post("/notifications/read-all")
async def mark_all_read(principal: PrincipalDep, session: SessionDep) -> dict[str, int]:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == principal.user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
    return {"marked": result.rowcount or 0}


@router.get("/notifications/settings", response_model=SettingsOut)
async def read_settings(principal: PrincipalDep, session: SessionDep) -> SettingsOut:
    s = await get_settings(session, principal.user.id)
    await session.commit()
    return SettingsOut.model_validate(s)


@router.put("/notifications/settings", response_model=SettingsOut)
async def write_settings(
    body: SettingsIn, principal: PrincipalDep, session: SessionDep
) -> SettingsOut:
    s = await get_settings(session, principal.user.id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    await session.commit()
    return SettingsOut.model_validate(s)


# --- device metrics ------------------------------------------------------------


class MetricsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_percent: float | None = Field(default=None, ge=0, le=100)
    disk_free_gb: float | None = Field(default=None, ge=0)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    charging: bool | None = None
    network: str | None = Field(default=None, max_length=40)
    uptime_hours: float | None = Field(default=None, ge=0)


class DeviceMetricsOut(BaseModel):
    device_id: uuid.UUID
    device_name: str
    platform: str
    metrics: dict[str, Any] | None
    updated_at: datetime | None


@router.post("/devices/metrics", status_code=status.HTTP_204_NO_CONTENT)
async def push_metrics(
    body: MetricsIn, principal: PrincipalDep, redis: RedisDep, settings: SettingsDep
) -> None:
    payload = {**body.model_dump(exclude_none=True), "at": datetime.now(UTC).isoformat()}
    await redis.set(
        redis_key(settings, "metrics", str(principal.device.id)),
        json.dumps(payload),
        ex=METRICS_TTL,
    )


async def read_metrics(redis: Any, settings: Any, device_id: uuid.UUID) -> dict[str, Any] | None:
    raw = await redis.get(redis_key(settings, "metrics", str(device_id)))
    return json.loads(raw) if raw else None


@router.get("/devices/metrics", response_model=list[DeviceMetricsOut])
async def list_metrics(
    principal: PrincipalDep, session: SessionDep, redis: RedisDep, settings: SettingsDep
) -> list[DeviceMetricsOut]:
    devices = await session.scalars(
        select(Device).where(Device.user_id == principal.user.id, Device.revoked_at.is_(None))
    )
    out = []
    for d in devices:
        m = await read_metrics(redis, settings, d.id)
        if m is None:
            continue
        at = datetime.fromisoformat(m.pop("at"))
        out.append(
            DeviceMetricsOut(
                device_id=d.id, device_name=d.name, platform=d.platform, metrics=m, updated_at=at
            )
        )
    return out
