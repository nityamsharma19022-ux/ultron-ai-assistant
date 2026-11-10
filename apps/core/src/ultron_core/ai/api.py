"""AI status and routing-preference endpoints (/api/v1/ai/...)."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, status

from ultron_core import ratelimit
from ultron_core.ai import profiles
from ultron_core.ai.errors import ModelNotInstalledError, ProviderError, ProviderNotConfiguredError
from ultron_core.ai.router import AIRouter
from ultron_core.ai.types import ProviderKind
from ultron_core.chat import service
from ultron_core.chat.schemas import (
    AIStatus,
    PreferencesIn,
    PreferencesOut,
    ProviderStatus,
    WarmupResult,
)
from ultron_core.deps import PrincipalDep, RedisDep, SessionDep, SettingsDep

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AIStatus)
async def ai_status(
    request: Request, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> AIStatus:
    """Which providers can answer right now. Never includes credentials."""
    ai_router: AIRouter = request.app.state.ai_router
    prefs = await service.get_preferences(session, principal.user)
    items: list[ProviderStatus] = []
    for provider in ai_router.providers:
        configured = provider.is_configured()
        cooldown = await ai_router.cooldowns.get(provider.name) if configured else None
        availability = await provider.availability()
        if not configured:
            state = "not_configured"
        elif cooldown is not None:
            state = f"cooldown_{cooldown.code}"
        elif not availability.available:
            state = "unavailable"
        else:
            state = "ready"
        loaded = None
        check = getattr(provider, "model_loaded", None)
        if state == "ready" and check is not None:
            loaded = await check()
        items.append(
            ProviderStatus(
                name=provider.name,
                kind=provider.kind.value,
                model=provider.model,
                configured=configured,
                available=state == "ready",
                status=state,
                reason=availability.reason,
                cooldown_remaining_seconds=round(cooldown.remaining) if cooldown else None,
                model_loaded=loaded,
            )
        )
    local_ready = any(i.available for i in items if i.kind == ProviderKind.LOCAL.value)
    return AIStatus(
        mode=prefs.mode,
        cloud_available=any(i.available for i in items if i.kind == ProviderKind.CLOUD.value),
        local_ai_available=local_ready,
        private_conversations_supported=settings.private_conversations_allowed and local_ready,
        providers=items,
        task_profiles=profiles.parse(settings.ai_task_profiles),
    )


def _prefs_out(prefs, ai_router: AIRouter) -> PreferencesOut:  # type: ignore[no-untyped-def]
    return PreferencesOut(
        mode=prefs.mode,
        cloud_order=list(prefs.cloud_order),
        private_by_default=prefs.private_by_default,
        memory_enabled=prefs.memory_enabled,
        available_cloud_providers=[p.name for p in ai_router.cloud_providers],
    )


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(
    request: Request, principal: PrincipalDep, session: SessionDep
) -> PreferencesOut:
    prefs = await service.get_preferences(session, principal.user)
    return _prefs_out(prefs, request.app.state.ai_router)


@router.put("/preferences", response_model=PreferencesOut)
async def put_preferences(
    body: PreferencesIn, request: Request, principal: PrincipalDep, session: SessionDep
) -> PreferencesOut:
    ai_router: AIRouter = request.app.state.ai_router
    known = {p.name for p in ai_router.cloud_providers}
    order = [name.strip().lower() for name in body.cloud_order]
    unknown = sorted(set(order) - known)
    if unknown or len(set(order)) != len(order):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"cloud_order must list distinct known cloud providers; unknown: {unknown}",
        )
    prefs = await service.get_preferences(session, principal.user)
    prefs.mode = body.mode
    prefs.cloud_order = order
    prefs.private_by_default = body.private_by_default
    if body.memory_enabled is not None:
        prefs.memory_enabled = body.memory_enabled
    session.add(prefs)
    await session.commit()
    return _prefs_out(prefs, ai_router)


@router.post("/local/warmup", response_model=WarmupResult)
async def warmup_local_model(
    request: Request, principal: PrincipalDep, settings: SettingsDep, redis: RedisDep
) -> WarmupResult:
    """Load the local model into memory so the first reply starts quickly.

    The app can call this at startup or when the user opens a chat."""
    if not await ratelimit.allow(
        redis, settings, bucket="warmup", identity=str(principal.user.id), limit=6, window=60
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many warm-up requests")
    ai_router: AIRouter = request.app.state.ai_router
    provider = next((p for p in ai_router.local_providers if hasattr(p, "warmup")), None)
    if provider is None or not provider.is_configured():
        reason = provider.missing_configuration() if provider else "no local AI provider"
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Local AI is not set up: {reason}")
    started = time.perf_counter()
    try:
        already = await provider.warmup()  # type: ignore[attr-defined]
    except ModelNotInstalledError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
    return WarmupResult(
        status="ready",
        provider=provider.name,
        model=provider.model,
        already_loaded=already,
        seconds=round(time.perf_counter() - started, 2),
    )
