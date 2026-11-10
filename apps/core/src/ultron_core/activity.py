"""User-visible activity history (audit log).

Every action ULTRON takes on the user's behalf is recorded here: memory
changes, tasks, steps, permission changes. Summaries are short and never
contain secrets.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.db.models import ActivityEvent
from ultron_core.deps import PrincipalDep, SessionDep


def record(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    summary: str,
    *,
    device_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> ActivityEvent:
    """Adds an event to the session; the caller commits."""
    event = ActivityEvent(
        user_id=user_id,
        device_id=device_id,
        task_id=task_id,
        kind=kind,
        summary=summary[:500],
        detail=detail or {},
    )
    session.add(event)
    return event


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    kind: str
    summary: str
    detail: dict[str, Any]
    device_id: uuid.UUID | None
    task_id: uuid.UUID | None
    created_at: Any


router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityOut])
async def list_activity(
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    before_seq: int | None = Query(default=None, ge=1),
    task_id: uuid.UUID | None = None,
) -> list[ActivityOut]:
    """Newest first. Page with ``before_seq``."""
    query = select(ActivityEvent).where(ActivityEvent.user_id == principal.user.id)
    if before_seq is not None:
        query = query.where(ActivityEvent.seq < before_seq)
    if task_id is not None:
        query = query.where(ActivityEvent.task_id == task_id)
    rows = await session.scalars(query.order_by(ActivityEvent.seq.desc()).limit(limit))
    return [ActivityOut.model_validate(r) for r in rows]
