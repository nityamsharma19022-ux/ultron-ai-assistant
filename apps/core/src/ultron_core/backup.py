"""Exporting your ULTRON data (GET /api/v1/export, `ultron-core export`).

A readable JSON copy of what ULTRON stores for you: conversations and
messages, memories, tasks, reminders, schedules, operating modes, settings
and recent activity. Never included: password hash, sign-in tokens, device
keys, document file contents. Private items (which only exist on a local
backend) are left out unless asked for.

The full database backup remains `pg_dump` (docs/ULTRON_SETUP_GUIDE.md).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core import activity
from ultron_core.db.models import (
    ActivityEvent,
    AssistantMode,
    AutomationState,
    Conversation,
    Document,
    Memory,
    Message,
    Notification,
    NotificationSettings,
    PermissionGrant,
    Reminder,
    Schedule,
    Task,
    TaskStep,
    User,
    UserAIPreferences,
)
from ultron_core.deps import PrincipalDep, SessionDep

FORMAT = "ultron-export/1"
SKIP_COLUMNS = {"search", "user_id", "version"}
MAX_ACTIVITY = 2000
MAX_NOTIFICATIONS = 500

router = APIRouter(tags=["backup"])


def _row(obj: Any, skip: set[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in inspect(obj).mapper.column_attrs:
        key = attr.key
        if key in SKIP_COLUMNS or (skip and key in skip):
            continue
        value = getattr(obj, key)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        out[key] = value
    return out


async def export_user(
    session: AsyncSession, user: User, *, include_private: bool = False
) -> dict[str, Any]:
    uid = user.id

    def visible(model: Any) -> Any:
        stmt = select(model).where(model.user_id == uid)
        if not include_private and hasattr(model, "is_private"):
            stmt = stmt.where(model.is_private.is_(False))
        return stmt

    conversations = []
    convs = await session.scalars(
        visible(Conversation)
        .where(Conversation.deleted_at.is_(None))
        .order_by(Conversation.created_at)
    )
    for conv in convs:
        messages = await session.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq)
        )
        conversations.append(
            {**_row(conv, {"deleted_at"}), "messages": [_row(m) for m in messages]}
        )

    tasks = []
    for task in await session.scalars(visible(Task).order_by(Task.created_at)):
        steps = await session.scalars(
            select(TaskStep).where(TaskStep.task_id == task.id).order_by(TaskStep.idx)
        )
        tasks.append({**_row(task), "steps": [_row(s, {"task_id"}) for s in steps]})

    async def rows(stmt: Any) -> list[dict[str, Any]]:
        return [_row(r) for r in await session.scalars(stmt)]

    async def one(model: Any) -> dict[str, Any] | None:
        obj = await session.get(model, uid)
        return _row(obj) if obj is not None else None

    return {
        "format": FORMAT,
        "exported_at": datetime.now(UTC).isoformat(),
        "includes_private": include_private,
        "user": {"email": user.email, "display_name": user.display_name},
        "preferences": await one(UserAIPreferences),
        "automation": await one(AutomationState),
        "notification_settings": await one(NotificationSettings),
        "permissions": await rows(visible(PermissionGrant)),
        "modes": await rows(visible(AssistantMode)),
        "conversations": conversations,
        "memories": await rows(visible(Memory).order_by(Memory.created_at)),
        "tasks": tasks,
        "reminders": await rows(visible(Reminder).order_by(Reminder.due_at)),
        "schedules": await rows(visible(Schedule)),
        "documents": await rows(visible(Document).order_by(Document.created_at)),
        "notifications": await rows(
            visible(Notification).order_by(Notification.created_at.desc()).limit(MAX_NOTIFICATIONS)
        ),
        "activity": await rows(
            visible(ActivityEvent).order_by(ActivityEvent.created_at.desc()).limit(MAX_ACTIVITY)
        ),
    }


@router.get("/export")
async def export_data(
    principal: PrincipalDep,
    session: SessionDep,
    include_private: bool = Query(default=False),
) -> dict[str, Any]:
    data = await export_user(session, principal.user, include_private=include_private)
    activity.record(
        session,
        principal.user.id,
        "data.exported",
        "Exported your ULTRON data" + (" (including private items)" if include_private else ""),
        device_id=principal.device.id,
    )
    await session.commit()
    return data
