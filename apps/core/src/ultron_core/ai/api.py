"""AI status and routing-preference endpoints (/api/v1/ai/...)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ultron_core.ai.router import AIRouter
from ultron_core.ai.types import ProviderKind
from ultron_core.chat import service
from ultron_core.chat.schemas import AIStatus, PreferencesIn, PreferencesOut, ProviderStatus
from ultron_core.deps import PrincipalDep, SessionDep, SettingsDep

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
            )
        )
    local_ready = any(i.available for i in items if i.kind == ProviderKind.LOCAL.value)
    return AIStatus(
        mode=prefs.mode,
        cloud_available=any(i.available for i in items if i.kind == ProviderKind.CLOUD.value),
        local_ai_available=local_ready,
        private_conversations_supported=settings.private_conversations_allowed and local_ready,
        providers=items,
    )


def _prefs_out(prefs, ai_router: AIRouter) -> PreferencesOut:  # type: ignore[no-untyped-def]
    return PreferencesOut(
        mode=prefs.mode,
        cloud_order=list(prefs.cloud_order),
        private_by_default=prefs.private_by_default,
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
    session.add(prefs)
    await session.commit()
    return _prefs_out(prefs, ai_router)
