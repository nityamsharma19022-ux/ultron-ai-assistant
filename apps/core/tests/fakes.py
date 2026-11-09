"""Scriptable fake AI providers: no network, no API keys, no cost."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from ultron_core.ai.errors import ProviderError
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.types import (
    Availability,
    ChatRequest,
    ProviderKind,
    StreamEnd,
    StreamEvent,
    TextDelta,
)


class FakeProvider(ChatProvider):
    def __init__(
        self,
        name: str,
        kind: ProviderKind,
        *,
        chunks: Sequence[str] = ("Hello", " from", " ULTRON"),
        error: ProviderError | None = None,
        error_after: int | None = None,
        configured: bool = True,
        available: bool = True,
        unavailable_reason: str = "local model 'llama3.2' is not installed",
        context_char_budget: int = 100_000,
        block: asyncio.Event | None = None,
    ) -> None:
        self.name = name
        self.kind = kind
        self.model = f"{name}-model"
        self.context_char_budget = context_char_budget
        self.chunks = list(chunks)
        self.error = error
        self.error_after = error_after
        self.configured = configured
        self.available = available
        self.unavailable_reason = unavailable_reason
        self.block = block
        self.started = asyncio.Event()
        self.calls: list[ChatRequest] = []

    def is_configured(self) -> bool:
        return self.configured

    def missing_configuration(self) -> str | None:
        return None if self.configured else "missing API key"

    async def availability(self) -> Availability:
        if not self.configured:
            return Availability(False, "missing API key")
        if self.kind is ProviderKind.LOCAL and not self.available:
            return Availability(False, self.unavailable_reason)
        return Availability(True)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append(request)
        self.started.set()
        if self.block is not None:
            await self.block.wait()
        if self.error is not None and self.error_after is None:
            raise self.error
        for i, chunk in enumerate(self.chunks):
            if self.error is not None and self.error_after == i:
                raise self.error
            await asyncio.sleep(0)
            yield TextDelta(chunk)
        yield StreamEnd(finish_reason="stop", input_tokens=10, output_tokens=len(self.chunks))


def cloud(name: str = "fake-cloud", **kw: object) -> FakeProvider:
    return FakeProvider(name, ProviderKind.CLOUD, **kw)  # type: ignore[arg-type]


def local(name: str = "fake-local", **kw: object) -> FakeProvider:
    kw.setdefault("chunks", ("Local", " reply"))
    return FakeProvider(name, ProviderKind.LOCAL, **kw)  # type: ignore[arg-type]
