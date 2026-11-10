"""Task API models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


class StepIn(_Strict):
    tool: str = Field(min_length=1, max_length=60)
    args: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(_Strict):
    """A task with an explicit plan (the Control Center's task builder)."""

    title: str = Field(min_length=1, max_length=200)
    steps: list[StepIn] = Field(min_length=1, max_length=10)
    private: bool = False

    _t = field_validator("title")(_text)


class CommandIn(_Strict):
    """Anything the user says or types: a task to do or a question."""

    text: str = Field(min_length=1, max_length=4000)
    timezone: str | None = Field(default=None, max_length=64)
    # Used when the device can't name its time zone (minutes east of UTC).
    utc_offset_minutes: int | None = Field(default=None, ge=-14 * 60, le=14 * 60)
    private: bool = False
    source: Literal["text", "voice", "assistant"] = "text"
    # Wait (up to the server limit) for the task to finish, for voice replies.
    wait: bool = False

    _t = field_validator("text")(_text)


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idx: int
    tool: str
    args: dict[str, Any]
    title: str
    target: str
    risk: str
    scope: str
    status: str
    approved: bool
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    error: str | None
    progress: str | None
    started_at: datetime | None
    finished_at: datetime | None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    request: str
    status: str
    plan_source: str
    is_private: bool
    summary: str | None
    error: str | None
    schedule_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[StepOut]


class CommandOut(BaseModel):
    type: Literal["task", "answer"]
    message: str
    task: TaskOut | None = None


class ApproveIn(_Strict):
    # "Always allow" for the routine (class A) steps in this task.
    remember: bool = False


class RepeatIn(_Strict):
    every: Literal["hourly", "daily", "weekly"]
    at: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    timezone: str | None = Field(default=None, max_length=64)


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    request: str
    every: str
    next_run_at: datetime
    enabled: bool
    last_task_id: uuid.UUID | None


class ScheduleUpdate(_Strict):
    enabled: bool


class PermissionOut(BaseModel):
    scope: str
    title: str
    granted: bool
    always_asks: bool
    expires_at: datetime | None
    tools: list[str]


class PermissionUpdate(_Strict):
    enabled: bool
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class AutomationOut(BaseModel):
    enabled: bool
    stopped: bool
    stopped_at: datetime | None
    levels: dict[str, int] = Field(default_factory=dict)
    level_names: dict[int, str] = Field(default_factory=dict)


class AutomationUpdate(_Strict):
    enabled: bool | None = None
    # false clears an emergency stop.
    stopped: bool | None = None
    # Autonomy level 0-5 per area.
    levels: dict[Literal["core", "pc", "phone"], int] | None = None

    @field_validator("levels")
    @classmethod
    def _levels(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is not None and any(not 0 <= lv <= 5 for lv in v.values()):
            raise ValueError("levels are 0 to 5")
        return v


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    due_at: datetime
    done: bool
    delivered_at: datetime | None
    task_id: uuid.UUID | None


class ReminderUpdate(_Strict):
    done: bool | None = None
    delivered: bool | None = None
