"""Creating tasks from requests or plans."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core import activity
from ultron_core.auth.service import Principal
from ultron_core.db.models import AgentInfo, Task, TaskStep
from ultron_core.tasks.engine import agent_online
from ultron_core.tasks.planner import Plan, PlanContext, zone

PLATFORM_TARGET = {"windows": "windows", "android": "android"}


async def plan_context(
    session: AsyncSession, principal: Principal, timezone: str | None
) -> PlanContext:
    agents = await session.scalars(select(AgentInfo).where(AgentInfo.user_id == principal.user.id))
    targets = {"core"}
    capabilities: dict[str, dict[str, Any]] = {}
    device_tools: set[str] = set()
    for agent in agents:
        if agent_online(agent) and agent.tools:
            targets.add(agent.target)
            device_tools.update(agent.tools)
            for key, values in agent.capabilities.items():
                merged = capabilities.setdefault(agent.target, {}).setdefault(key, [])
                merged.extend(v for v in values if v not in merged)
    return PlanContext(
        targets=targets,
        capabilities=capabilities,
        device_tools=device_tools,
        origin=PLATFORM_TARGET.get(principal.device.platform),
        tz=zone(timezone),
    )


async def create_task(
    session: AsyncSession,
    principal: Principal,
    plan: Plan,
    *,
    request: str,
    private: bool,
) -> Task:
    task = Task(
        user_id=principal.user.id,
        device_id=principal.device.id,
        title=plan.title[:200] or request[:200],
        request=request,
        status="queued",
        plan_source=plan.source,
        is_private=private,
    )
    for idx, s in enumerate(plan.steps):
        task.steps.append(
            TaskStep(
                idx=idx,
                tool=s.tool,
                args=s.args,
                title=s.title,
                target=s.target,
                risk=s.risk,
                scope=s.scope,
                max_attempts=s.max_attempts,
                status="pending",
                approved=False,
                attempts=0,
            )
        )
    session.add(task)
    await session.flush()
    activity.record(
        session,
        principal.user.id,
        "task.created",
        f"New task: {task.title}",
        task_id=task.id,
        device_id=principal.device.id,
        detail={"steps": len(plan.steps), "source": plan.source},
    )
    await session.commit()
    return task


def schedule_steps(task: Task) -> list[dict[str, Any]]:
    """A task's plan in the form a schedule stores."""
    return [
        {
            "tool": s.tool,
            "args": s.args,
            "title": s.title,
            "target": s.target,
            "risk": s.risk,
            "scope": s.scope,
            "max_attempts": s.max_attempts,
            "status": "pending",
        }
        for s in task.steps
    ]
