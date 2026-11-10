"""Who may run what without asking.

- Master switch off, or emergency stop active: nothing runs ("blocked");
  tasks wait until automation is turned back on.
- Class B and C actions always ask, every time, at every autonomy level.
- Class A actions depend on the area's autonomy level (core, pc, phone):

  0 Answer only      the area's tools aren't offered at all
  1 Suggest          every step waits for approval
  2 Prepare          read-only steps run, changes wait for approval
  3 Execute approved granted scopes run, others ask (default)
  4 Safe routines    every routine (class A) step runs
  5 Workflows        as 4, and plans may be longer
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.db.models import AutomationState, PermissionGrant
from ultron_core.tasks.tools import ALWAYS_ASK_SCOPES

Decision = Literal["auto", "ask", "blocked"]

AREAS = ("core", "pc", "phone")
DEFAULT_LEVEL = 3
LEVEL_NAMES = {
    0: "Answer only",
    1: "Suggest",
    2: "Prepare",
    3: "Execute approved",
    4: "Safe routines",
    5: "Complex workflows",
}
# Steps that only read or report (allowed at level 2).
READ_ONLY_SCOPES = {
    "memory.read",
    "docs.read",
    "web.read",
    "pc.system",
    "pc.files.read",
    "phone.system",
}


def area_of(scope_or_tool: str) -> str:
    if scope_or_tool.startswith("pc."):
        return "pc"
    if scope_or_tool.startswith("phone."):
        return "phone"
    return "core"


@dataclass
class Policy:
    enabled: bool = True
    stopped: bool = False
    grants: dict[str, PermissionGrant] = field(default_factory=dict)
    levels: dict[str, int] = field(default_factory=dict)

    def level(self, area: str) -> int:
        return int(self.levels.get(area, DEFAULT_LEVEL))

    def granted(self, scope: str, now: datetime | None = None) -> bool:
        grant = self.grants.get(scope)
        if grant is None or not grant.enabled:
            return False
        now = now or datetime.now(UTC)
        return grant.expires_at is None or grant.expires_at > now

    def decide(self, *, scope: str, risk: str, approved: bool) -> Decision:
        if not self.enabled or self.stopped:
            return "blocked"
        if approved:
            return "auto"
        if risk != "A" or scope in ALWAYS_ASK_SCOPES:
            return "ask"
        level = self.level(area_of(scope))
        if level <= 1:
            return "ask"
        if level == 2:
            return "auto" if scope in READ_ONLY_SCOPES else "ask"
        if level == 3:
            return "auto" if self.granted(scope) else "ask"
        return "auto"


async def automation_state(session: AsyncSession, user_id: uuid.UUID) -> AutomationState:
    state = await session.get(AutomationState, user_id)
    if state is None:
        state = AutomationState(user_id=user_id, enabled=True, stopped_at=None, levels={})
        session.add(state)
        await session.flush()
    return state


async def load_policy(session: AsyncSession, user_id: uuid.UUID) -> Policy:
    state = await session.get(AutomationState, user_id)
    grants = await session.scalars(
        select(PermissionGrant).where(PermissionGrant.user_id == user_id)
    )
    return Policy(
        enabled=state.enabled if state else True,
        stopped=bool(state and state.stopped_at),
        grants={g.scope: g for g in grants},
        levels=dict(state.levels or {}) if state else {},
    )


def can_remember(scope: str, risk: str) -> bool:
    """Whether "always allow" may be offered for this kind of step."""
    return risk == "A" and scope not in ALWAYS_ASK_SCOPES
