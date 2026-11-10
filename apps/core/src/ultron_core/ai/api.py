"""AI status and routing-preference endpoints (/api/v1/ai/...)."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from ultron_core import ratelimit
from ultron_core.ai import profiles
from ultron_core.ai.errors import ModelNotInstalledError, ProviderError, ProviderNotConfiguredError
from ultron_core.ai.router import AIRouter
from ultron_core.ai.types import ChatMessage, ChatRequest, ProviderKind, StreamEnd, TextDelta
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
        processor = None
        check = getattr(provider, "model_loaded", None)
        if state == "ready" and check is not None:
            loaded = await check()
            where = getattr(provider, "processor", None)
            if loaded and where is not None:
                processor = await where()
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
                processor=processor,
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
        memory_saving_paused=prefs.memory_saving_paused,
        time_format=prefs.time_format,
        address_as=prefs.address_as,
        response_mode=prefs.response_mode,
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
    if body.memory_saving_paused is not None:
        prefs.memory_saving_paused = body.memory_saving_paused
    for field in ("time_format", "address_as", "response_mode"):
        value = getattr(body, field)
        if value is not None:
            setattr(prefs, field, value)
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


class ProviderTestOut(BaseModel):
    provider: str
    kind: str
    ok: bool
    model: str | None = None
    seconds: float
    reply: str | None = None
    error: str | None = None


@router.post("/providers/{name}/test", response_model=ProviderTestOut)
async def test_provider(
    name: str, request: Request, principal: PrincipalDep, settings: SettingsDep, redis: RedisDep
) -> ProviderTestOut:
    """Sends one tiny message through ULTRON Core to this provider, so you can
    check that Core itself (not just your PC) reaches it. Uses a little of
    the provider's free quota, so it is rate-limited."""
    if not await ratelimit.allow(
        redis, settings, bucket="ai-test", identity=str(principal.user.id), limit=10, window=60
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many tests; wait a minute"
        )
    ai_router: AIRouter = request.app.state.ai_router
    provider = next((p for p in ai_router.providers if p.name == name.lower()), None)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown AI provider")
    started = time.perf_counter()
    reply, model, error = "", provider.model, None
    if not provider.is_configured():
        error = f"Not set up: {provider.missing_configuration()}"
    else:
        probe = ChatRequest(
            messages=(ChatMessage(role="user", content="Reply with the single word: ready"),),
            system="You are a connection test. Answer with one word.",
            max_output_tokens=16,
        )
        try:
            async with asyncio.timeout(settings.ai_request_timeout_seconds):
                async for event in provider.stream(probe):
                    if isinstance(event, TextDelta):
                        reply += event.text
                    elif isinstance(event, StreamEnd) and event.model:
                        model = event.model
        except ProviderError as exc:
            error = exc.message
        except TimeoutError:
            error = "No answer in time"
    ok = error is None and bool(reply.strip())
    if error is None and not ok:
        error = "The provider answered with an empty reply"
    return ProviderTestOut(
        provider=provider.name,
        kind=provider.kind.value,
        ok=ok,
        model=model,
        seconds=round(time.perf_counter() - started, 2),
        reply=reply.strip()[:200] or None,
        error=error,
    )


class UsageRow(BaseModel):
    provider: str
    kind: str | None
    model: str | None
    replies: int
    failed: int
    fallbacks: int
    input_tokens: int
    output_tokens: int
    # Measured on the server (successful replies only), in milliseconds.
    avg_first_token_ms: int | None = None
    avg_duration_ms: int | None = None


class UsageOut(BaseModel):
    days: int
    total_replies: int
    rows: list[UsageRow]


@router.get("/usage", response_model=UsageOut)
async def usage(
    principal: PrincipalDep, session: SessionDep, days: int = Query(default=7, ge=1, le=90)
) -> UsageOut:
    """How many replies each AI source and model produced (your account only)."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import case, func, select

    from ultron_core.db.models import Conversation, Message

    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(
            Message.provider,
            Message.provider_kind,
            Message.model,
            func.count(),
            func.sum(case((Message.status == "failed", 1), else_=0)),
            func.sum(case((Message.fallback_used.is_(True), 1), else_=0)),
            func.coalesce(func.sum(Message.input_tokens), 0),
            func.coalesce(func.sum(Message.output_tokens), 0),
            func.avg(case((Message.status == "complete", Message.first_token_ms))),
            func.avg(case((Message.status == "complete", Message.duration_ms))),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.user_id == principal.user.id,
            Message.role == "assistant",
            Message.created_at >= since,
            Message.provider.is_not(None),
        )
        .group_by(Message.provider, Message.provider_kind, Message.model)
        .order_by(func.count().desc())
    )
    rows = [
        UsageRow(
            provider=p,
            kind=k,
            model=m,
            replies=n,
            failed=int(f or 0),
            fallbacks=int(fb or 0),
            input_tokens=int(i),
            output_tokens=int(o),
            avg_first_token_ms=round(ft) if ft is not None else None,
            avg_duration_ms=round(d) if d is not None else None,
        )
        for p, k, m, n, f, fb, i, o, ft, d in (await session.execute(stmt)).all()
    ]
    return UsageOut(days=days, total_replies=sum(r.replies for r in rows), rows=rows)
