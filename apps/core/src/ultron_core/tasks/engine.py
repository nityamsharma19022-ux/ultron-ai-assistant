"""Runs tasks step by step.

One background loop per server process. It wakes when something changes
(a task is created or approved, an agent reports a result) and every
couple of seconds otherwise. For each active task it looks at the next
step:

- not allowed yet  -> the step and the task wait for the user's approval;
- automation off   -> the task waits;
- Core tool        -> runs here, in its own asyncio task;
- device tool      -> marked "ready"; the device's agent claims it, runs it
                      and reports back (see agents.py).

Ordinary failures are retried with a short backoff; a step that keeps
failing fails the task. Every transition is written to the activity log.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from ultron_core import activity
from ultron_core.ai.router import AIRouter
from ultron_core.chat.service import get_preferences, routing_preferences
from ultron_core.config import Settings
from ultron_core.db.models import AgentInfo, Schedule, Task, TaskStep, User
from ultron_core.logging_setup import get_logger
from ultron_core.tasks import core_tools, permissions, tools
from ultron_core.tasks.tools import ToolError

log = get_logger("ultron.tasks.engine")

ACTIVE = ("queued", "running")
TERMINAL = ("completed", "failed", "cancelled")
AGENT_ONLINE_SECONDS = 90
RETRY_BACKOFF_SECONDS = (2, 10, 30)


def now() -> datetime:
    return datetime.now(UTC)


def agent_online(agent: AgentInfo, at: datetime | None = None) -> bool:
    return (at or now()) - agent.last_seen_at < timedelta(seconds=AGENT_ONLINE_SECONDS)


def resolve_args(step: TaskStep, steps: list[TaskStep]) -> dict[str, Any]:
    """Fills ``content_from_step`` with the text an earlier step produced."""
    args = dict(step.args)
    ref = args.pop("content_from_step", None)
    if ref is not None:
        source = steps[ref].result or {}
        text = source.get("text")
        if not isinstance(text, str):
            raise ToolError(f"Step {ref + 1} produced no text to use.")
        args["content"] = text
    return args


def task_summary(task: Task) -> str:
    lines = []
    for step in task.steps:
        result = step.result or {}
        note = result.get("summary") if isinstance(result, dict) else None
        if step.status == "succeeded":
            lines.append(f"✓ {step.title}" + (f" — {note}" if note else ""))
        elif step.status == "failed":
            lines.append(f"✗ {step.title} — {step.error or 'failed'}")
        elif step.status in ("skipped", "cancelled"):
            lines.append(f"- {step.title} ({step.status})")
    return "\n".join(lines)


class TaskEngine:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        router: AIRouter,
        settings: Settings,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.router = router
        self.settings = settings
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._core_runs: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self.tick_seconds = 2.0
        self.redis = None  # set by the app; enables proactive rules
        self.http = None  # httpx.AsyncClient (set by the app) for web.read
        self.proactive_every = timedelta(seconds=30)
        self._last_proactive = datetime.min.replace(tzinfo=UTC)

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._loop(), name="ultron-task-engine")

    async def stop(self) -> None:
        tasks = [t for t in [self._loop_task, *self._core_runs.values()] if t and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._loop_task = None

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        await self.recover()
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("tasks.tick_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.tick_seconds)
            self._wake.clear()

    async def recover(self) -> None:
        """After a restart, Core steps that were running are retried."""
        async with self.sessionmaker() as s:
            rows = await s.scalars(
                select(TaskStep).where(TaskStep.target == "core", TaskStep.status == "running")
            )
            for step in rows:
                step.status = "pending"
                step.progress = "Restarted after ULTRON Core restarted"
            await s.commit()

    # --- the scheduler -------------------------------------------------------

    async def tick(self) -> None:
        async with self._lock:
            await self._run_schedules()
            await self._run_proactive()
            async with self.sessionmaker() as s:
                ids = list(await s.scalars(select(Task.id).where(Task.status.in_(ACTIVE))))
            for task_id in ids:
                await self.advance(task_id)

    async def advance(self, task_id: uuid.UUID) -> None:
        async with self.sessionmaker() as s:
            task = await s.scalar(
                select(Task).where(Task.id == task_id).options(selectinload(Task.steps))
            )
            if task is None or task.status not in ACTIVE:
                return
            policy = await permissions.load_policy(s, task.user_id)
            for step in task.steps:
                if step.status in ("succeeded", "skipped"):
                    continue
                if step.status == "failed":
                    await self._finish(s, task, "failed", step.error)
                    return
                if step.status == "cancelled":
                    await self._finish(s, task, "cancelled", None)
                    return
                if step.status == "running":
                    await self._check_stuck(s, task, step)
                    return
                if step.status == "ready":
                    await self._check_waiting(s, task, step)
                    return
                # pending or awaiting_approval
                if step.not_before and step.not_before > now():
                    return
                decision = policy.decide(scope=step.scope, risk=step.risk, approved=step.approved)
                if decision == "blocked":
                    if step.progress != "Waiting: automation is paused":
                        step.progress = "Waiting: automation is paused"
                        await s.commit()
                    return
                if decision == "ask":
                    if step.status != "awaiting_approval":
                        step.status = "awaiting_approval"
                        task.status = "awaiting_approval"
                        activity.record(
                            s,
                            task.user_id,
                            "task.approval_needed",
                            f"Needs your approval: {step.title}",
                            task_id=task.id,
                            detail={"risk": step.risk, "scope": step.scope},
                        )
                        await s.commit()
                    return
                await self._start_step(s, task, step)
                return
            await self._finish(s, task, "completed", None)

    async def _start_step(self, s: AsyncSession, task: Task, step: TaskStep) -> None:
        if task.status != "running":
            task.status = "running"
            task.started_at = task.started_at or now()
        if step.target == "core":
            step.status = "running"
            step.attempts += 1
            step.started_at = now()
            step.progress = None
            await s.commit()
            self._core_runs[step.id] = asyncio.create_task(
                self._run_core(task.id, step.id), name=f"ultron-step-{step.id}"
            )
            return
        step.status = "ready"
        step.started_at = now()  # used for the device wait timeout
        step.progress = "Waiting for your " + ("PC" if step.target == "windows" else "phone")
        await s.commit()

    async def _run_core(self, task_id: uuid.UUID, step_id: uuid.UUID) -> None:
        try:
            async with self.sessionmaker() as s:
                task = await s.scalar(
                    select(Task).where(Task.id == task_id).options(selectinload(Task.steps))
                )
                step = next((x for x in task.steps if x.id == step_id), None) if task else None
                if task is None or step is None or step.status != "running":
                    return
                user = await s.get(User, task.user_id)
                assert user is not None  # noqa: S101
                prefs = routing_preferences(await get_preferences(s, user))
                ctx = core_tools.CoreContext(
                    session=s,
                    task=task,
                    router=self.router,
                    prefs=prefs,
                    settings=self.settings,
                    results={x.idx: x.result or {} for x in task.steps if x.status == "succeeded"},
                    http=self.http,
                )
                try:
                    spec, args = tools.validate_step(step.tool, resolve_args(step, task.steps))
                    async with asyncio.timeout(self.settings.ai_max_reply_seconds):
                        result = await core_tools.run(spec.name, args, ctx)
                except ToolError as exc:
                    await self.record_failure(s, task, step, exc.message, exc.retryable)
                    return
                except TimeoutError:
                    await self.record_failure(s, task, step, "Timed out", True)
                    return
                except Exception:
                    log.exception("tasks.core_tool_crashed", tool=step.tool)
                    await self.record_failure(s, task, step, "Internal error", False)
                    return
                await self.record_success(s, task, step, result)
        finally:
            self._core_runs.pop(step_id, None)
            self.wake()

    # --- results (from Core tools and agents) --------------------------------

    async def record_success(
        self, s: AsyncSession, task: Task, step: TaskStep, result: dict[str, Any]
    ) -> None:
        if result.get("verified") is False:
            await self.record_failure(
                s,
                task,
                step,
                str(result.get("summary") or "The result could not be verified"),
                False,
            )
            return
        step.status = "succeeded"
        step.result = result
        step.error = None
        step.progress = None
        step.finished_at = now()
        activity.record(
            s,
            task.user_id,
            "step.succeeded",
            f"{step.title}" + (f" — {result['summary']}" if result.get("summary") else ""),
            task_id=task.id,
            device_id=step.assigned_device_id,
            detail={"tool": step.tool},
        )
        await s.commit()
        self.wake()

    async def record_failure(
        self, s: AsyncSession, task: Task, step: TaskStep, error: str, retryable: bool
    ) -> None:
        error = error[:1000]
        if retryable and step.attempts < step.max_attempts and task.status in ACTIVE:
            delay = RETRY_BACKOFF_SECONDS[min(step.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            step.status = "pending"
            step.not_before = now() + timedelta(seconds=delay)
            step.progress = f"Retrying after an error: {error[:200]}"
            step.assigned_device_id = None
            activity.record(
                s,
                task.user_id,
                "step.retrying",
                f"Retrying: {step.title} ({error[:150]})",
                task_id=task.id,
                detail={"tool": step.tool, "attempt": step.attempts},
            )
        else:
            step.status = "failed"
            step.error = error
            step.finished_at = now()
            activity.record(
                s,
                task.user_id,
                "step.failed",
                f"Failed: {step.title} — {error[:200]}",
                task_id=task.id,
                detail={"tool": step.tool},
            )
        await s.commit()
        self.wake()

    async def _check_waiting(self, s: AsyncSession, task: Task, step: TaskStep) -> None:
        limit = timedelta(minutes=self.settings.task_device_wait_minutes)
        if step.started_at and now() - step.started_at > limit:
            device = "PC" if step.target == "windows" else "phone"
            step.attempts += 1
            await self.record_failure(
                s,
                task,
                step,
                f"Your {device} didn't connect within {self.settings.task_device_wait_minutes} "
                "minutes. Make sure the ULTRON agent is running, then retry.",
                False,
            )

    async def _check_stuck(self, s: AsyncSession, task: Task, step: TaskStep) -> None:
        if step.target == "core":
            return  # the asyncio task reports itself
        limit = timedelta(minutes=self.settings.task_step_timeout_minutes)
        if step.started_at and now() - step.started_at > limit:
            await self.record_failure(s, task, step, "The device stopped responding", True)

    async def _finish(self, s: AsyncSession, task: Task, status: str, error: str | None) -> None:
        for step in task.steps:
            if step.status in ("pending", "awaiting_approval", "ready"):
                step.status = "skipped" if status == "failed" else "cancelled"
        task.status = status
        task.error = error
        task.finished_at = now()
        task.summary = task_summary(task)
        if status == "failed":
            from ultron_core.notifications import notify

            await notify(
                s,
                task.user_id,
                "task.failed",
                f"Task failed: {task.title}",
                error or "",
                priority="high",
                task_id=task.id,
                dedupe_key=f"failed:{task.id}",
            )
        verb = {"completed": "Completed", "failed": "Failed", "cancelled": "Cancelled"}[status]
        activity.record(
            s,
            task.user_id,
            f"task.{status}",
            f"{verb}: {task.title}",
            task_id=task.id,
            detail={"error": error} if error else None,
        )
        await s.commit()

    # --- user controls ------------------------------------------------------

    async def cancel(self, s: AsyncSession, task: Task, reason: str = "Cancelled") -> None:
        for step in task.steps:
            if step.status in ("pending", "awaiting_approval", "ready", "running"):
                if step.status == "running":
                    run = self._core_runs.get(step.id)
                    if run is not None:
                        run.cancel()
                step.status = "cancelled"
                step.finished_at = now()
        task.status = "cancelled"
        task.finished_at = now()
        task.summary = task_summary(task)
        activity.record(
            s, task.user_id, "task.cancelled", f"{reason}: {task.title}", task_id=task.id
        )
        await s.commit()

    async def _run_proactive(self, force: bool = False) -> None:
        if self.redis is None or (
            not force and now() - self._last_proactive < self.proactive_every
        ):
            return
        self._last_proactive = now()
        from ultron_core import proactive

        try:
            async with self.sessionmaker() as s:
                await proactive.run(s, self.redis, self.settings)
        except Exception:
            log.exception("tasks.proactive_failed")

    # --- recurring tasks ----------------------------------------------------

    async def _run_schedules(self) -> None:
        async with self.sessionmaker() as s:
            due = list(
                await s.scalars(
                    select(Schedule).where(
                        Schedule.enabled.is_(True), Schedule.next_run_at <= now()
                    )
                )
            )
            for sched in due:
                task = Task(
                    user_id=sched.user_id,
                    schedule_id=sched.id,
                    title=sched.title,
                    request=sched.request,
                    status="queued",
                    plan_source="schedule",
                    is_private=False,
                )
                for idx, raw in enumerate(sched.steps):
                    task.steps.append(TaskStep(idx=idx, approved=False, attempts=0, **raw))
                s.add(task)
                await s.flush()
                sched.last_task_id = task.id
                step_delta = {"hourly": timedelta(hours=1), "daily": timedelta(days=1)}.get(
                    sched.every, timedelta(weeks=1)
                )
                while sched.next_run_at <= now():
                    sched.next_run_at += step_delta
                activity.record(
                    s,
                    sched.user_id,
                    "task.scheduled_run",
                    f"Started recurring task: {sched.title}",
                    task_id=task.id,
                )
            await s.commit()
