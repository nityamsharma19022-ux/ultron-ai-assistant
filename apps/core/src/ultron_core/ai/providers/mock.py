"""Development-only mock provider: lets the app be built and demoed without
any API key or local model. Refused in production (see config validation)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.types import ChatRequest, ProviderKind, StreamEnd, StreamEvent, TextDelta


class DevMockProvider(ChatProvider):
    def __init__(self, kind: ProviderKind, delay_seconds: float = 0.02) -> None:
        self.kind = kind
        self.name = f"mock-{kind.value}"
        self.model = "ultron-dev-mock"
        self.context_char_budget = 8000
        self._delay = delay_seconds

    def is_configured(self) -> bool:
        return True

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        last = request.messages[-1].content if request.messages else ""
        reply = f"[ULTRON dev mock, {self.kind.value}] You said: {last[:200]}"
        for word in reply.split(" "):
            await asyncio.sleep(self._delay)
            yield TextDelta(word + " ")
        yield StreamEnd(finish_reason="stop", model=self.model)
