"""Operating modes (/api/v1/modes).

A mode changes how ULTRON behaves: its personality (added to the AI's
instructions), which AI routing to use, whether memories are used, which
areas it may act in, and whether non-urgent notifications stay quiet.
Built-in modes are defined here; users can add their own.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core import activity
from ultron_core.chat.service import get_preferences
from ultron_core.db.models import AssistantMode, User
from ultron_core.deps import PrincipalDep, SessionDep

ALL_AREAS = ["core", "pc", "phone"]


@dataclass(frozen=True)
class Mode:
    key: str
    name: str
    personality: str = ""
    ai_mode: str | None = None  # None: use the user's routing preference
    memory: bool = True
    tool_areas: list[str] = field(default_factory=lambda: list(ALL_AREAS))
    quiet: bool = False
    builtin: bool = True

    def prompt(self) -> str:
        if not self.personality:
            return ""
        return f"\n\nCurrent mode: {self.name}. {self.personality}"


BUILTIN: dict[str, Mode] = {
    m.key: m
    for m in [
        Mode("normal", "Normal assistant"),
        Mode(
            "work",
            "Work and productivity",
            "Be concise and action-oriented. Focus on tasks, deadlines, priorities and clear "
            "next steps.",
        ),
        Mode(
            "developer",
            "Developer",
            "Act as a senior software engineer. Be precise and technical; show code, commands "
            "and file paths; prefer correctness over brevity; point out risks.",
        ),
        Mode(
            "study",
            "Study and learning",
            "Act as a patient tutor. Explain step by step with examples, check understanding, "
            "and suggest practice questions.",
        ),
        Mode(
            "focus",
            "Focus",
            "Keep answers very short. Don't suggest new topics or tasks unless asked.",
            quiet=True,
        ),
    ]
}


def _from_row(row: AssistantMode) -> Mode:
    return Mode(
        key=row.key,
        name=row.name,
        personality=row.personality,
        ai_mode=row.ai_mode,
        memory=row.memory,
        tool_areas=list(row.tool_areas),
        quiet=row.quiet,
        builtin=False,
    )


async def all_modes(session: AsyncSession, user_id: uuid.UUID) -> list[Mode]:
    rows = await session.scalars(
        select(AssistantMode).where(AssistantMode.user_id == user_id).order_by(AssistantMode.name)
    )
    return [*BUILTIN.values(), *(_from_row(r) for r in rows)]


async def active_mode(session: AsyncSession, user: User) -> Mode:
    key = (await get_preferences(session, user)).active_mode or "normal"
    if key in BUILTIN:
        return BUILTIN[key]
    row = await session.scalar(
        select(AssistantMode).where(AssistantMode.user_id == user.id, AssistantMode.key == key)
    )
    return _from_row(row) if row else BUILTIN["normal"]


# --- API -----------------------------------------------------------------------

router = APIRouter(prefix="/modes", tags=["modes"])
Area = Literal["core", "pc", "phone"]


class ModeOut(BaseModel):
    key: str
    name: str
    personality: str
    ai_mode: str | None
    memory: bool
    tool_areas: list[str]
    quiet: bool
    builtin: bool
    active: bool


class ModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    personality: str = Field(default="", max_length=2000)
    ai_mode: Literal["auto", "cloud_only", "local_only"] | None = None
    memory: bool = True
    tool_areas: list[Area] = Field(default_factory=lambda: list(ALL_AREAS))
    quiet: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ActiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=40)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "mode"


def _out(mode: Mode, active: str) -> ModeOut:
    data = asdict(mode)
    return ModeOut(**data, active=mode.key == active)


@router.get("", response_model=list[ModeOut])
async def list_modes(principal: PrincipalDep, session: SessionDep) -> list[ModeOut]:
    current = (await active_mode(session, principal.user)).key
    return [_out(m, current) for m in await all_modes(session, principal.user.id)]


@router.put("/active", response_model=ModeOut)
async def set_active(body: ActiveIn, principal: PrincipalDep, session: SessionDep) -> ModeOut:
    modes = {m.key: m for m in await all_modes(session, principal.user.id)}
    mode = modes.get(body.key)
    if mode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such mode")
    prefs = await get_preferences(session, principal.user)
    prefs.active_mode = mode.key
    session.add(prefs)
    activity.record(
        session,
        principal.user.id,
        "mode.changed",
        f"Switched to {mode.name} mode",
        device_id=principal.device.id,
    )
    await session.commit()
    return _out(mode, mode.key)


@router.post("", response_model=ModeOut, status_code=status.HTTP_201_CREATED)
async def create_mode(body: ModeIn, principal: PrincipalDep, session: SessionDep) -> ModeOut:
    existing = {m.key for m in await all_modes(session, principal.user.id)}
    key, n = _slug(body.name), 2
    while key in existing:
        key, n = f"{_slug(body.name)[:36]}-{n}", n + 1
    row = AssistantMode(user_id=principal.user.id, key=key, **body.model_dump())
    session.add(row)
    await session.commit()
    current = (await active_mode(session, principal.user)).key
    return _out(_from_row(row), current)


async def _custom(session: AsyncSession, user_id: uuid.UUID, key: str) -> AssistantMode:
    if key in BUILTIN:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Built-in modes can't be changed")
    row = await session.scalar(
        select(AssistantMode).where(AssistantMode.user_id == user_id, AssistantMode.key == key)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such mode")
    return row


@router.put("/{key}", response_model=ModeOut)
async def update_mode(
    key: str, body: ModeIn, principal: PrincipalDep, session: SessionDep
) -> ModeOut:
    row = await _custom(session, principal.user.id, key)
    for name, value in body.model_dump().items():
        setattr(row, name, value)
    await session.commit()
    current = (await active_mode(session, principal.user)).key
    return _out(_from_row(row), current)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mode(key: str, principal: PrincipalDep, session: SessionDep) -> Response:
    row = await _custom(session, principal.user.id, key)
    prefs = await get_preferences(session, principal.user)
    if prefs.active_mode == key:
        prefs.active_mode = "normal"
        session.add(prefs)
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
