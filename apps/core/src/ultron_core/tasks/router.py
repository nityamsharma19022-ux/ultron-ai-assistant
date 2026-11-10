"""Task, permission, automation, schedule and reminder endpoints, and the
unified assistant command (/api/v1/assistant/command)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ultron_core import activity
from ultron_core.ai import profiles
from ultron_core.chat.service import get_preferences, routing_preferences
from ultron_core.db.models import PermissionGrant, Reminder, Schedule, Task
from ultron_core.deps import PrincipalDep, SessionDep, SettingsDep
from ultron_core.tasks import permissions, planner, service, tools
from ultron_core.tasks.engine import TERMINAL, TaskEngine
from ultron_core.tasks.schemas import (
    ApproveIn,
    AutomationOut,
    AutomationUpdate,
    CommandIn,
    CommandOut,
    PermissionOut,
    PermissionUpdate,
    ReminderOut,
    ReminderUpdate,
    RepeatIn,
    ScheduleOut,
    ScheduleUpdate,
    TaskCreate,
    TaskOut,
)

router = APIRouter(tags=["tasks"])

PRIVATE_NOT_ALLOWED = "Private tasks need a local ULTRON backend with a local database."


def _engine(request: Request) -> TaskEngine:
    return request.app.state.task_engine


async def _load(session: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = await session.scalar(
        select(Task).where(Task.id == task_id).options(selectinload(Task.steps))
    )
    if task is None or task.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


async def _out(session: AsyncSession, task_id: uuid.UUID) -> TaskOut:
    # Fresh copies of this task and its steps only (other objects, like the
    # signed-in user, stay loaded).
    task = await session.scalar(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.steps))
        .execution_options(populate_existing=True)
    )
    return TaskOut.model_validate(task)


# --- the assistant command ------------------------------------------------------


def _task_message(task: TaskOut) -> str:
    if task.status == "completed":
        notes = [
            str(s.result["summary"]).rstrip(".")
            for s in task.steps
            if s.result and isinstance(s.result.get("summary"), str)
        ]
        if len(task.steps) == 1 and notes:
            return f"Done. {notes[0]}."
        return f"Done: {task.title.rstrip('.')} ({len(task.steps)} steps)."
    if task.status == "awaiting_approval":
        waiting = [s.title for s in task.steps if s.status == "awaiting_approval"]
        return "I need your approval to: " + "; ".join(waiting or [task.title])
    if task.status == "failed":
        return f"I couldn't finish that. {task.error or ''}".strip()
    if task.status == "cancelled":
        return "That task was cancelled."
    waiting = next((s.progress for s in task.steps if s.status == "ready" and s.progress), None)
    return f"Working on it: {task.title}" + (f". {waiting}." if waiting else "")


async def _wait(session: AsyncSession, task_id: uuid.UUID, seconds: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        task = await session.get(Task, task_id, populate_existing=True)
        if task is None or task.status in (*TERMINAL, "awaiting_approval"):
            return
        await asyncio.sleep(0.2)


@router.post("/assistant/command", response_model=CommandOut)
async def assistant_command(
    body: CommandIn,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CommandOut:
    if body.private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    ctx = await service.plan_context(session, principal, body.timezone, body.utc_offset_minutes)
    plan = planner.rule_plan(body.text, ctx)
    if plan is None:
        prefs = routing_preferences(await get_preferences(session, principal.user))
        prefs = profiles.preferences_for("planning", prefs, settings.ai_task_profiles)
        try:
            plan = await planner.ai_plan(
                body.text, ctx, request.app.state.ai_router, prefs, private=body.private
            )
        except planner.PlanError as exc:
            return CommandOut(type="answer", message=f"I couldn't plan that: {exc.message}")
    if not plan.steps:
        return CommandOut(
            type="answer", message=plan.answer or "I'm not sure how to help with that."
        )
    task = await service.create_task(
        session, principal, plan, request=body.text, private=body.private
    )
    engine = _engine(request)
    engine.wake()
    if body.wait:
        await _wait(session, task.id, settings.assistant_wait_seconds)
    out = await _out(session, task.id)
    return CommandOut(type="task", message=_task_message(out), task=out)


# --- tasks ---------------------------------------------------------------------


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> TaskOut:
    if body.private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    ctx = await service.plan_context(session, principal, None)
    try:
        steps = planner.build_steps(
            [s.model_dump() for s in body.steps],
            max_steps=ctx.max_steps,
            allowed_areas=ctx.allowed_areas,
        )
    except planner.PlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from None
    plan = planner.Plan(title=body.title, steps=steps, source="manual")
    task = await service.create_task(
        session, principal, plan, request=body.title, private=body.private
    )
    _engine(request).wake()
    return await _out(session, task.id)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    principal: PrincipalDep,
    session: SessionDep,
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[TaskOut]:
    query = select(Task).where(Task.user_id == principal.user.id).options(selectinload(Task.steps))
    if status_filter == "active":
        query = query.where(Task.status.not_in(TERMINAL))
    elif status_filter:
        query = query.where(Task.status == status_filter)
    rows = await session.scalars(query.order_by(Task.created_at.desc()).limit(limit).offset(offset))
    return [TaskOut.model_validate(t) for t in rows]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> TaskOut:
    return TaskOut.model_validate(await _load(session, principal.user.id, task_id))


@router.post("/tasks/{task_id}/approve", response_model=TaskOut)
async def approve_task(
    task_id: uuid.UUID,
    body: ApproveIn,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> TaskOut:
    task = await _load(session, principal.user.id, task_id)
    waiting = [s for s in task.steps if s.status in ("awaiting_approval", "pending")]
    if task.status != "awaiting_approval" or not waiting:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This task isn't waiting for approval")
    for step in waiting:
        step.approved = True
        step.status = "pending"
        if body.remember and permissions.can_remember(step.scope, step.risk):
            grant = await session.get(PermissionGrant, (principal.user.id, step.scope))
            if grant is None:
                session.add(
                    PermissionGrant(user_id=principal.user.id, scope=step.scope, enabled=True)
                )
            else:
                grant.enabled, grant.expires_at = True, None
    task.status = "queued"
    activity.record(
        session,
        principal.user.id,
        "task.approved",
        f"You approved: {task.title}",
        task_id=task.id,
        device_id=principal.device.id,
        detail={"remember": body.remember},
    )
    await session.commit()
    _engine(request).wake()
    return await _out(session, task.id)


async def _control(
    request: Request, principal: Any, session: AsyncSession, task_id: uuid.UUID, action: str
) -> TaskOut:
    engine = _engine(request)
    task = await _load(session, principal.user.id, task_id)
    if action in ("cancel", "reject"):
        if task.status in TERMINAL:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="The task has already finished")
        await engine.cancel(
            session, task, "You declined" if action == "reject" else "You cancelled"
        )
    elif action == "pause":
        if task.status not in ("queued", "running", "awaiting_approval"):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only active tasks can be paused")
        task.status = "paused"
        activity.record(
            session, principal.user.id, "task.paused", f"Paused: {task.title}", task_id=task.id
        )
        await session.commit()
    elif action == "resume":
        if task.status != "paused":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="The task isn't paused")
        task.status = "queued"
        activity.record(
            session, principal.user.id, "task.resumed", f"Resumed: {task.title}", task_id=task.id
        )
        await session.commit()
    elif action == "retry":
        if task.status not in ("failed", "cancelled"):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Only failed or cancelled tasks can be retried"
            )
        for step in task.steps:
            if step.status != "succeeded":
                step.status, step.attempts, step.error = "pending", 0, None
                step.progress, step.not_before, step.assigned_device_id = None, None, None
        task.status, task.error, task.finished_at = "queued", None, None
        activity.record(
            session, principal.user.id, "task.retried", f"Retrying: {task.title}", task_id=task.id
        )
        await session.commit()
    engine.wake()
    return await _out(session, task.id)


def _control_route(action: str) -> None:
    async def endpoint(
        task_id: uuid.UUID, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> TaskOut:
        return await _control(request, principal, session, task_id, action)

    endpoint.__name__ = f"{action}_task"
    router.add_api_route(
        f"/tasks/{{task_id}}/{action}", endpoint, methods=["POST"], response_model=TaskOut
    )


for _action in ("cancel", "reject", "pause", "resume", "retry"):
    _control_route(_action)


def _next_run(every: str, at: str | None, tz_name: str | None) -> datetime:
    now = datetime.now(UTC)
    if every == "hourly" or not at:
        return now + {"hourly": timedelta(hours=1), "daily": timedelta(days=1)}.get(
            every, timedelta(weeks=1)
        )
    tz = planner.zone(tz_name)
    hour, minute = (int(x) for x in at.split(":"))
    if hour > 23 or minute > 59:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid time")
    local_now = now.astimezone(tz)
    run = datetime.combine(local_now.date(), time(hour, minute), tzinfo=tz)
    while run <= local_now:
        run += timedelta(days=1)
    return run.astimezone(UTC)


@router.post(
    "/tasks/{task_id}/repeat", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED
)
async def repeat_task(
    task_id: uuid.UUID, body: RepeatIn, principal: PrincipalDep, session: SessionDep
) -> ScheduleOut:
    task = await _load(session, principal.user.id, task_id)
    if task.is_private:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Private tasks can't be repeated")
    sched = Schedule(
        user_id=principal.user.id,
        title=task.title,
        request=task.request,
        steps=service.schedule_steps(task),
        every=body.every,
        next_run_at=_next_run(body.every, body.at, body.timezone),
        enabled=True,
    )
    session.add(sched)
    activity.record(
        session,
        principal.user.id,
        "schedule.created",
        f"Repeats {body.every}: {task.title}",
        task_id=task.id,
    )
    await session.commit()
    return ScheduleOut.model_validate(sched)


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(principal: PrincipalDep, session: SessionDep) -> list[ScheduleOut]:
    rows = await session.scalars(
        select(Schedule).where(Schedule.user_id == principal.user.id).order_by(Schedule.next_run_at)
    )
    return [ScheduleOut.model_validate(r) for r in rows]


async def _schedule(session: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID) -> Schedule:
    sched = await session.get(Schedule, sid)
    if sched is None or sched.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return sched


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID, body: ScheduleUpdate, principal: PrincipalDep, session: SessionDep
) -> ScheduleOut:
    sched = await _schedule(session, principal.user.id, schedule_id)
    sched.enabled = body.enabled
    await session.commit()
    return ScheduleOut.model_validate(sched)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> Response:
    await session.delete(await _schedule(session, principal.user.id, schedule_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- permissions and automation ------------------------------------------------


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(principal: PrincipalDep, session: SessionDep) -> list[PermissionOut]:
    policy = await permissions.load_policy(session, principal.user.id)
    out = []
    for scope, title in tools.SCOPES.items():
        grant = policy.grants.get(scope)
        out.append(
            PermissionOut(
                scope=scope,
                title=title,
                granted=policy.granted(scope),
                always_asks=scope in tools.ALWAYS_ASK_SCOPES,
                expires_at=grant.expires_at if grant else None,
                tools=[t.name for t in tools.TOOLS.values() if t.scope == scope],
            )
        )
    return out


@router.put("/permissions/{scope}", response_model=PermissionOut)
async def set_permission(
    scope: str, body: PermissionUpdate, principal: PrincipalDep, session: SessionDep
) -> PermissionOut:
    if scope not in tools.SCOPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown permission")
    if body.enabled and scope in tools.ALWAYS_ASK_SCOPES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This permission always asks")
    grant = await session.get(PermissionGrant, (principal.user.id, scope))
    expires = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    )
    if grant is None:
        grant = PermissionGrant(user_id=principal.user.id, scope=scope)
        session.add(grant)
    grant.enabled, grant.expires_at = body.enabled, expires
    activity.record(
        session,
        principal.user.id,
        "permission.granted" if body.enabled else "permission.revoked",
        f"{'Allowed' if body.enabled else 'Revoked'}: {tools.SCOPES[scope]}",
        device_id=principal.device.id,
        detail={"scope": scope},
    )
    await session.commit()
    policy = await permissions.load_policy(session, principal.user.id)
    return PermissionOut(
        scope=scope,
        title=tools.SCOPES[scope],
        granted=policy.granted(scope),
        always_asks=False,
        expires_at=grant.expires_at,
        tools=[t.name for t in tools.TOOLS.values() if t.scope == scope],
    )


def _automation_out(state: Any) -> AutomationOut:
    levels = {
        a: int((state.levels or {}).get(a, permissions.DEFAULT_LEVEL)) for a in permissions.AREAS
    }
    return AutomationOut(
        enabled=state.enabled,
        stopped=bool(state.stopped_at),
        stopped_at=state.stopped_at,
        levels=levels,
        level_names=permissions.LEVEL_NAMES,
    )


@router.get("/automation", response_model=AutomationOut)
async def get_automation(principal: PrincipalDep, session: SessionDep) -> AutomationOut:
    state = await permissions.automation_state(session, principal.user.id)
    await session.commit()
    return _automation_out(state)


@router.put("/automation", response_model=AutomationOut)
async def set_automation(
    body: AutomationUpdate, request: Request, principal: PrincipalDep, session: SessionDep
) -> AutomationOut:
    state = await permissions.automation_state(session, principal.user.id)
    if body.enabled is not None:
        state.enabled = body.enabled
        activity.record(
            session,
            principal.user.id,
            "automation.switched",
            f"Automation turned {'on' if body.enabled else 'off'}",
            device_id=principal.device.id,
        )
    if body.levels:
        state.levels = {**(state.levels or {}), **body.levels}
        changes = ", ".join(
            f"{a}: {permissions.LEVEL_NAMES[lv]}" for a, lv in sorted(body.levels.items())
        )
        activity.record(
            session,
            principal.user.id,
            "automation.levels",
            f"Autonomy changed ({changes})",
            device_id=principal.device.id,
        )
    if body.stopped is False and state.stopped_at:
        state.stopped_at = None
        activity.record(
            session,
            principal.user.id,
            "automation.resumed",
            "Emergency stop cleared",
            device_id=principal.device.id,
        )
    await session.commit()
    _engine(request).wake()
    return _automation_out(state)


@router.post("/automation/emergency-stop", response_model=AutomationOut)
async def emergency_stop(
    request: Request, principal: PrincipalDep, session: SessionDep
) -> AutomationOut:
    """Stops everything at once: cancels every active task and blocks new
    ones from running until the stop is cleared."""
    state = await permissions.automation_state(session, principal.user.id)
    state.stopped_at = datetime.now(UTC)
    activity.record(
        session,
        principal.user.id,
        "automation.emergency_stop",
        "Emergency stop",
        device_id=principal.device.id,
    )
    await session.commit()
    engine = _engine(request)
    active = await session.scalars(
        select(Task)
        .where(Task.user_id == principal.user.id, Task.status.not_in(TERMINAL))
        .options(selectinload(Task.steps))
    )
    for task in list(active):
        await engine.cancel(session, task, "Emergency stop")
    return _automation_out(state)


# --- reminders -----------------------------------------------------------------


@router.get("/reminders", response_model=list[ReminderOut])
async def list_reminders(
    principal: PrincipalDep,
    session: SessionDep,
    due: bool = Query(default=False, description="Only due, undelivered reminders"),
    include_done: bool = False,
) -> list[ReminderOut]:
    query = select(Reminder).where(Reminder.user_id == principal.user.id)
    if due:
        query = query.where(
            Reminder.due_at <= datetime.now(UTC),
            Reminder.delivered_at.is_(None),
            Reminder.done.is_(False),
        )
    elif not include_done:
        query = query.where(Reminder.done.is_(False))
    rows = await session.scalars(query.order_by(Reminder.due_at).limit(200))
    return [ReminderOut.model_validate(r) for r in rows]


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: uuid.UUID, body: ReminderUpdate, principal: PrincipalDep, session: SessionDep
) -> ReminderOut:
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != principal.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    if body.done is not None:
        reminder.done = body.done
    if body.delivered:
        reminder.delivered_at = reminder.delivered_at or datetime.now(UTC)
    await session.commit()
    return ReminderOut.model_validate(reminder)


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> Response:
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != principal.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    await session.delete(reminder)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
