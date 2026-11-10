"""Agent protocol: devices that run steps (/api/v1/agents).

An agent is a signed-in device (the Windows agent, the Android app). It:

1. says hello with the tools it can run and a description of its local
   setup (folder names, app names, workflow names; no secrets);
2. long-polls for the next step meant for its kind of device;
3. reports progress and the result.

An agent only receives steps for tools it announced, for its own user, and
only after Core's permission check has passed. The agent applies its own
local allow-lists as well.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ultron_core.auth.service import Principal
from ultron_core.db.models import AgentInfo, Device, Task, TaskStep
from ultron_core.deps import PrincipalDep, SessionDep
from ultron_core.tasks import tools
from ultron_core.tasks.engine import ACTIVE, TaskEngine, agent_online, resolve_args
from ultron_core.tasks.tools import ToolError

router = APIRouter(prefix="/agents", tags=["agents"])

TARGETS = {"windows": "windows", "android": "android"}
MAX_WAIT = 25


class HelloIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[str] = Field(max_length=100)
    capabilities: dict[str, list[str]] = Field(default_factory=dict, max_length=10)
    version: str | None = Field(default=None, max_length=40)


class AgentOut(BaseModel):
    device_id: uuid.UUID
    device_name: str
    target: str
    online: bool
    last_seen_at: datetime
    agent_version: str | None
    tools: list[str]
    capabilities: dict[str, Any]


class StepWork(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    tool: str
    args: dict[str, Any]
    title: str
    attempt: int


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=300)


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=1000)
    retryable: bool = False


class StepControl(BaseModel):
    cancel: bool


def _target(principal: Principal) -> str:
    target = TARGETS.get(principal.device.platform)
    if target is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Only Windows and Android devices can be agents"
        )
    return target


async def _agent(session: AsyncSession, principal: Principal) -> AgentInfo:
    agent = await session.get(AgentInfo, principal.device.id)
    if agent is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Say hello first (POST /agents/hello)")
    return agent


def _clean_caps(caps: dict[str, list[str]]) -> dict[str, list[str]]:
    allowed = ("roots", "apps", "workflows")
    return {k: [str(v)[:100] for v in caps.get(k, [])][:100] for k in allowed if k in caps}


@router.post("/hello", response_model=AgentOut)
async def hello(
    body: HelloIn, principal: PrincipalDep, session: SessionDep, request: Request
) -> AgentOut:
    target = _target(principal)
    prefix = "pc." if target == "windows" else "phone."
    known = [t for t in body.tools if t in tools.TOOLS and t.startswith(prefix)]
    agent = await session.get(AgentInfo, principal.device.id)
    if agent is None:
        agent = AgentInfo(device_id=principal.device.id, user_id=principal.user.id, target=target)
        session.add(agent)
    agent.tools = known
    agent.capabilities = _clean_caps(body.capabilities)
    agent.agent_version = body.version
    agent.last_seen_at = datetime.now(UTC)
    await session.commit()
    request.app.state.task_engine.wake()
    return _out(agent, principal.device)


def _out(agent: AgentInfo, device: Device) -> AgentOut:
    return AgentOut(
        device_id=agent.device_id,
        device_name=device.name,
        target=agent.target,
        online=agent_online(agent),
        last_seen_at=agent.last_seen_at,
        agent_version=agent.agent_version,
        tools=list(agent.tools),
        capabilities=dict(agent.capabilities),
    )


@router.get("", response_model=list[AgentOut])
async def list_agents(principal: PrincipalDep, session: SessionDep) -> list[AgentOut]:
    rows = await session.execute(
        select(AgentInfo, Device)
        .join(Device, Device.id == AgentInfo.device_id)
        .where(AgentInfo.user_id == principal.user.id, Device.revoked_at.is_(None))
        .order_by(AgentInfo.last_seen_at.desc())
    )
    return [_out(a, d) for a, d in rows]


async def _claim(session: AsyncSession, principal: Principal, agent: AgentInfo) -> StepWork | None:
    agent.last_seen_at = datetime.now(UTC)
    step = await session.scalar(
        select(TaskStep)
        .join(Task, Task.id == TaskStep.task_id)
        .where(
            Task.user_id == principal.user.id,
            Task.status.in_(ACTIVE),
            TaskStep.status == "ready",
            TaskStep.target == agent.target,
            TaskStep.tool.in_(list(agent.tools) or [""]),
        )
        .order_by(TaskStep.created_at)
        .limit(1)
        .with_for_update(skip_locked=True, of=TaskStep)
    )
    if step is None:
        await session.commit()
        return None
    task = await session.scalar(
        select(Task).where(Task.id == step.task_id).options(selectinload(Task.steps))
    )
    assert task is not None  # noqa: S101
    try:
        args = resolve_args(step, task.steps)
    except ToolError as exc:
        step.status, step.error = "failed", exc.message
        await session.commit()
        return None
    step.status = "running"
    step.attempts += 1
    step.assigned_device_id = principal.device.id
    step.started_at = datetime.now(UTC)
    step.progress = "Started on " + principal.device.name
    await session.commit()
    return StepWork(
        id=step.id,
        task_id=task.id,
        task_title=task.title,
        tool=step.tool,
        args=args,
        title=step.title,
        attempt=step.attempts,
    )


@router.get("/steps/next", response_model=StepWork, responses={204: {"description": "No work"}})
async def next_step(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    wait: int = Query(default=20, ge=0, le=MAX_WAIT),
) -> Any:
    """Long poll: returns the next step, or 204 after ``wait`` seconds."""
    agent = await _agent(session, principal)
    engine: TaskEngine = request.app.state.task_engine
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        work = await _claim(session, principal, agent)
        if work is not None:
            engine.wake()
            return work
        if loop.time() >= deadline or await request.is_disconnected():
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        await asyncio.sleep(1.0)
        session.expire_all()
        agent = await _agent(session, principal)


async def _assigned_step(
    session: AsyncSession, principal: Principal, step_id: uuid.UUID
) -> tuple[Task, TaskStep]:
    step = await session.get(TaskStep, step_id)
    if step is None or step.assigned_device_id != principal.device.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Step not found")
    task = await session.scalar(
        select(Task).where(Task.id == step.task_id).options(selectinload(Task.steps))
    )
    assert task is not None  # noqa: S101
    step = next(s for s in task.steps if s.id == step_id)
    return task, step


@router.post("/steps/{step_id}/progress", response_model=StepControl)
async def step_progress(
    step_id: uuid.UUID, body: ProgressIn, principal: PrincipalDep, session: SessionDep
) -> StepControl:
    task, step = await _assigned_step(session, principal, step_id)
    cancel = task.status not in ACTIVE or step.status != "running"
    if not cancel:
        step.progress = body.message
    await session.commit()
    return StepControl(cancel=cancel)


@router.post("/steps/{step_id}/result", response_model=StepControl)
async def step_result(
    step_id: uuid.UUID,
    body: ResultIn,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> StepControl:
    task, step = await _assigned_step(session, principal, step_id)
    engine: TaskEngine = request.app.state.task_engine
    if step.status != "running":
        # Cancelled meanwhile: keep the outcome for the record only.
        step.result = {**body.result, "late": True}
        await session.commit()
        return StepControl(cancel=True)
    if body.ok:
        await engine.record_success(session, task, step, body.result)
    else:
        step.result = body.result or None
        await engine.record_failure(session, task, step, body.error or "Failed", body.retryable)
    return StepControl(cancel=False)
