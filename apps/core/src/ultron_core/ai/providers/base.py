"""The provider interface every AI adapter implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ultron_core.ai.types import Availability, ChatRequest, ProviderKind, StreamEvent


class ChatProvider(ABC):
    name: str
    kind: ProviderKind
    model: str | None
    # Rough context budget for this provider, in characters (~4 chars/token).
    context_char_budget: int

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials/model are present. Never makes a network call."""

    def missing_configuration(self) -> str | None:
        """Human-readable reason the provider is not configured (no secrets)."""
        return None if self.is_configured() else "not configured"

    async def availability(self) -> Availability:
        """Cloud providers are not pinged (that would spend quota); being
        configured is enough. Local providers override this with a real check."""
        if not self.is_configured():
            return Availability(False, self.missing_configuration())
        return Availability(True)

    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Yield TextDelta events then exactly one StreamEnd.

        Must raise only ``ultron_core.ai.errors.ProviderError`` subclasses."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release resources (HTTP clients)."""
