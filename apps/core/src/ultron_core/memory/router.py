"""Memory endpoints (/api/v1/memories)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ultron_core import activity
from ultron_core.db.models import Memory
from ultron_core.deps import PrincipalDep, SessionDep, SettingsDep
from ultron_core.memory import service

router = APIRouter(prefix="/memories", tags=["memory"])

Kind = Literal["preference", "fact", "project", "note"]
MAX_CONTENT = 2000
PRIVATE_NOT_ALLOWED = (
    "Private memories can only be stored on a local ULTRON backend with a local database."
)


def _clean(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_CONTENT)
    kind: Kind = "note"
    pinned: bool = False
    is_private: bool = False

    _clean = field_validator("content")(_clean)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=MAX_CONTENT)
    kind: Kind | None = None
    pinned: bool | None = None
    is_private: bool | None = None

    @field_validator("content")
    @classmethod
    def _clean_content(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    kind: str
    source: str
    is_private: bool
    pinned: bool
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")


def _preview(text: str) -> str:
    return text if len(text) <= 80 else text[:79] + "…"


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    principal: PrincipalDep,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200),
    kind: Kind | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[MemoryOut]:
    rows = await service.search(
        session, principal.user, query=q, kind=kind, limit=limit, offset=offset
    )
    return [MemoryOut.model_validate(m) for m in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: MemoryCreate, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> MemoryOut:
    if body.is_private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    memory = Memory(
        user_id=principal.user.id,
        content=body.content,
        kind=body.kind,
        pinned=body.pinned,
        is_private=body.is_private,
        source="user",
    )
    session.add(memory)
    activity.record(
        session,
        principal.user.id,
        "memory.created",
        "Saved a memory" if body.is_private else f"Saved a memory: {_preview(body.content)}",
        device_id=principal.device.id,
    )
    await session.commit()
    return MemoryOut.model_validate(memory)


@router.get("/export")
async def export_memories(principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
    rows = await service.search(session, principal.user, limit=10_000)
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "count": len(rows),
        "memories": [MemoryOut.model_validate(m).model_dump(mode="json") for m in rows],
    }


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> MemoryOut:
    try:
        memory = await service.get(session, principal.user, memory_id)
    except service.MemoryNotFoundError:
        raise _not_found() from None
    if body.is_private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    for field in ("content", "kind", "pinned", "is_private"):
        value = getattr(body, field)
        if value is not None:
            setattr(memory, field, value)
    activity.record(
        session,
        principal.user.id,
        "memory.updated",
        "Edited a memory",
        device_id=principal.device.id,
    )
    await session.commit()
    await session.refresh(memory)
    return MemoryOut.model_validate(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> Response:
    try:
        memory = await service.get(session, principal.user, memory_id)
    except service.MemoryNotFoundError:
        raise _not_found() from None
    await session.delete(memory)
    activity.record(
        session,
        principal.user.id,
        "memory.deleted",
        "Deleted a memory",
        device_id=principal.device.id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_all_memories(
    principal: PrincipalDep,
    session: SessionDep,
    confirm: Literal["delete-all"] = Query(description='Must be "delete-all"'),
) -> dict[str, int]:
    count = await service.delete_all(session, principal.user)
    activity.record(
        session,
        principal.user.id,
        "memory.deleted_all",
        f"Deleted all memories ({count})",
        device_id=principal.device.id,
    )
    await session.commit()
    return {"deleted": count}
