"""Cloud-first, local-fallback provider router.

Order of decisions for every reply:

1. Build the candidate list from the user's preferences:
   - ``auto``       -> cloud providers (in the preferred order), then local
   - ``cloud_only`` -> cloud providers only
   - ``local_only`` -> local providers only
   Private conversations keep **only local providers**, whatever the mode.
2. Skip providers that are not configured, are cooling down after a rate
   limit / quota / outage, or (local) whose model is not actually installed.
3. Try each remaining provider. A failure *before* the first token falls
   through to the next candidate; a connection failure marks the network as
   down so the remaining cloud providers are skipped (offline -> local).
4. A failure *after* text has been streamed is not retried elsewhere (one
   reply is never stitched together from two models); the partial reply is
   kept and marked incomplete.

Every reply reports which provider produced it (cloud or local) and whether
a fallback happened.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from ultron_core.ai.cooldown import CooldownStore
from ultron_core.ai.errors import ProviderError
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.types import ChatRequest, ProviderKind, StreamEnd, TextDelta
from ultron_core.logging_setup import get_logger

log = get_logger("ultron.ai.router")

RoutingMode = Literal["auto", "cloud_only", "local_only"]
ROUTING_MODES: tuple[RoutingMode, ...] = ("auto", "cloud_only", "local_only")


@dataclass(frozen=True, slots=True)
class RoutingPreferences:
    mode: RoutingMode = "auto"
    # Preferred order of cloud providers; unknown/omitted ones follow in
    # the server's default order.
    cloud_order: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Attempt:
    provider: str
    kind: ProviderKind
    outcome: str  # "ok" or an error/skip code
    detail: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "kind": self.kind.value,
            "outcome": self.outcome,
            "detail": self.detail,
        }


@dataclass(slots=True)
class RouteInfo:
    provider: str
    kind: ProviderKind
    model: str | None
    fallback_used: bool
    attempts: list[Attempt] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "kind": self.kind.value,
            "model": self.model,
            "fallback_used": self.fallback_used,
            "attempts": [a.as_dict() for a in self.attempts],
        }


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    """About to ask this provider (no reply text yet). Drives loading states."""

    provider: str
    kind: ProviderKind
    model: str | None


@dataclass(frozen=True, slots=True)
class ProviderSelected:
    route: RouteInfo


@dataclass(frozen=True, slots=True)
class Completed:
    route: RouteInfo
    end: StreamEnd


RouterEvent = ProviderAttempt | ProviderSelected | TextDelta | Completed


class RoutingError(Exception):
    """No reply could be produced. ``code`` and ``message`` are client-safe."""

    def __init__(self, code: str, message: str, attempts: Sequence[Attempt]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = list(attempts)


class MidStreamError(Exception):
    """The provider failed after part of the reply was already streamed."""

    def __init__(self, error: ProviderError, route: RouteInfo) -> None:
        super().__init__(error.message)
        self.error = error
        self.route = route


# Skip outcomes don't count as "a fallback happened"; real failures do.
_NEUTRAL_OUTCOMES = {"not_configured", "skipped_private", "ok"}


class AIRouter:
    def __init__(
        self,
        providers: Sequence[ChatProvider],
        cooldowns: CooldownStore,
        default_cloud_order: Sequence[str] = (),
    ) -> None:
        self.providers = list(providers)
        self.cooldowns = cooldowns
        self.default_cloud_order = list(default_cloud_order)

    @property
    def cloud_providers(self) -> list[ChatProvider]:
        return [p for p in self.providers if p.kind is ProviderKind.CLOUD]

    @property
    def local_providers(self) -> list[ChatProvider]:
        return [p for p in self.providers if p.kind is ProviderKind.LOCAL]

    def get(self, name: str) -> ChatProvider | None:
        return next((p for p in self.providers if p.name == name), None)

    def _ordered_cloud(self, preferred: Sequence[str]) -> list[ChatProvider]:
        rank: dict[str, int] = {}
        for name in [*preferred, *self.default_cloud_order]:
            rank.setdefault(name, len(rank))  # first mention wins: user's order first
        return sorted(self.cloud_providers, key=lambda p: rank.get(p.name, len(rank)))

    def candidates(self, prefs: RoutingPreferences, private: bool) -> list[ChatProvider]:
        if private or prefs.mode == "local_only":
            return self.local_providers
        cloud = self._ordered_cloud(prefs.cloud_order)
        if prefs.mode == "cloud_only":
            return cloud
        return [*cloud, *self.local_providers]

    async def stream(
        self,
        build_request: Callable[[ChatProvider], ChatRequest],
        prefs: RoutingPreferences,
        *,
        private: bool,
    ) -> AsyncIterator[RouterEvent]:
        attempts: list[Attempt] = []
        network_down = False

        for provider in self.candidates(prefs, private):
            # Belt and braces: a private conversation never reaches the cloud.
            if private and provider.kind is not ProviderKind.LOCAL:
                attempts.append(Attempt(provider.name, provider.kind, "skipped_private"))
                continue
            if not provider.is_configured():
                attempts.append(
                    Attempt(
                        provider.name,
                        provider.kind,
                        "not_configured",
                        provider.missing_configuration(),
                    )
                )
                continue
            if network_down and provider.kind is ProviderKind.CLOUD:
                attempts.append(Attempt(provider.name, provider.kind, "skipped_offline"))
                continue
            cooldown = await self.cooldowns.get(provider.name)
            if cooldown is not None:
                attempts.append(
                    Attempt(
                        provider.name,
                        provider.kind,
                        f"cooldown_{cooldown.code}",
                        f"{round(cooldown.remaining)}s remaining",
                    )
                )
                continue
            if provider.kind is ProviderKind.LOCAL:
                availability = await provider.availability()
                if not availability.available:
                    attempts.append(
                        Attempt(provider.name, provider.kind, "unavailable", availability.reason)
                    )
                    continue

            route = RouteInfo(
                provider=provider.name,
                kind=provider.kind,
                model=provider.model,
                fallback_used=any(a.outcome not in _NEUTRAL_OUTCOMES for a in attempts),
                attempts=attempts,
            )
            started = False
            end = StreamEnd(model=provider.model)
            yield ProviderAttempt(provider.name, provider.kind, provider.model)
            try:
                async for event in provider.stream(build_request(provider)):
                    if isinstance(event, TextDelta):
                        if not started:
                            started = True
                            yield ProviderSelected(route)
                        yield event
                    elif isinstance(event, StreamEnd):
                        end = event
            except ProviderError as exc:
                attempts.append(Attempt(provider.name, provider.kind, exc.code, exc.message))
                log.warning(
                    "ai.provider_failed",
                    provider=provider.name,
                    kind=provider.kind.value,
                    code=exc.code,
                    after_output=started,
                )
                if exc.effective_cooldown > 0:
                    await self.cooldowns.set(provider.name, exc.code, exc.effective_cooldown)
                if exc.network_down:
                    network_down = True
                if started:
                    raise MidStreamError(exc, route) from exc
                if not exc.fallback_allowed:
                    raise RoutingError(exc.code, exc.message, attempts) from exc
                continue

            if not started:
                yield ProviderSelected(route)
            if end.model:
                route.model = end.model
            attempts.append(Attempt(provider.name, provider.kind, "ok"))
            log.info(
                "ai.reply_routed",
                provider=provider.name,
                kind=provider.kind.value,
                fallback_used=route.fallback_used,
            )
            yield Completed(route, end)
            return

        raise self._no_provider_error(prefs, private, attempts, network_down)

    def _no_provider_error(
        self,
        prefs: RoutingPreferences,
        private: bool,
        attempts: list[Attempt],
        network_down: bool,
    ) -> RoutingError:
        local_attempt = next((a for a in attempts if a.kind is ProviderKind.LOCAL), None)
        local_reason = (local_attempt.detail if local_attempt else None) or "no local model set up"
        if private:
            return RoutingError(
                "private_requires_local_ai",
                "This conversation is private, so it can only use local AI, and local AI "
                f"is not available ({local_reason}).",
                attempts,
            )
        if prefs.mode == "local_only":
            return RoutingError(
                "local_ai_unavailable", f"Local AI is not available ({local_reason}).", attempts
            )
        if network_down:
            return RoutingError(
                "offline_no_local_ai",
                "Cloud AI can't be reached (you may be offline) and local AI is not "
                f"available ({local_reason}).",
                attempts,
            )
        if prefs.mode == "cloud_only":
            return RoutingError(
                "cloud_ai_unavailable",
                "No cloud AI provider is available right now.",
                attempts,
            )
        return RoutingError(
            "no_ai_available",
            "No AI provider is available: cloud providers are not configured or are "
            f"temporarily unavailable, and local AI is not available ({local_reason}).",
            attempts,
        )
