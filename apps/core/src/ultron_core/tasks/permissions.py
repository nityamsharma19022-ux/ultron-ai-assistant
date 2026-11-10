"""Who may run what without asking.

- Master switch off, or emergency stop active: nothing runs ("blocked");
  tasks wait until automation is turned back on.
- Class B and C actions always ask, every time.
- Class A actions run without asking when the user granted their scope and
  the grant hasn't expired; otherwise they ask once (the user can choose
  "always allow" when approving).
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


@dataclass
class Policy:
    enabled: bool = True
    stopped: bool = False
    grants: dict[str, PermissionGrant] = field(default_factory=dict)

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
        return "auto" if self.granted(scope) else "ask"


async def automation_state(session: AsyncSession, user_id: uuid.UUID) -> AutomationState:
    state = await session.get(AutomationState, user_id)
    if state is None:
        state = AutomationState(user_id=user_id, enabled=True, stopped_at=None)
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
    )


def can_remember(scope: str, risk: str) -> bool:
    """Whether "always allow" may be offered for this kind of step."""
    return risk == "A" and scope not in ALWAYS_ASK_SCOPES
