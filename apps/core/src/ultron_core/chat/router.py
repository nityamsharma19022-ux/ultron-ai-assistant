"""Chat endpoints (/api/v1/conversations...)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from ultron_core import persona, ratelimit, timefmt
from ultron_core.ai import profiles
from ultron_core.ai import speed as ai_speed
from ultron_core.ai.context import SYSTEM_PROMPT
from ultron_core.ai.router import RoutingPreferences
from ultron_core.chat import service
from ultron_core.chat.generation import ActiveGeneration, ConversationBusyError, GenerationManager
from ultron_core.chat.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageCreate,
    MessageOut,
    SearchHit,
    SendMessageResult,
)
from ultron_core.db.models import Conversation
from ultron_core.deps import PrincipalDep, RedisDep, SessionDep, SettingsDep
from ultron_core.documents import service as document_service
from ultron_core.memory import service as memory_service
from ultron_core.modes import active_mode

router = APIRouter(prefix="/conversations", tags=["chat"])

PRIVATE_NOT_ALLOWED = (
    "Private conversations are only available on a local ULTRON backend using a "
    "local database, so that their data stays on your own machine."
)


SPEED_PROMPTS = {
    "instant": "\nAnswer briefly and directly.",
    "balanced": "",
    "deep": "\nThink the problem through carefully and give a thorough, well-reasoned answer.",
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


async def _load(session, principal, conversation_id: uuid.UUID):  # type: ignore[no-untyped-def]
    try:
        return await service.get_conversation(session, principal.user, conversation_id)
    except service.ConversationNotFoundError:
        raise _not_found() from None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> ConversationOut:
    is_private = body.is_private
    if is_private is None:
        is_private = (await service.get_preferences(session, principal.user)).private_by_default
    if is_private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    conversation = Conversation(
        user_id=principal.user.id, title=body.title, is_private=is_private, project=body.project
    )
    session.add(conversation)
    await session.commit()
    return ConversationOut.model_validate(conversation)


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[ConversationOut]:
    rows = await service.list_conversations(session, principal.user, limit=limit, offset=offset)
    return [ConversationOut.model_validate(c) for c in rows]


@router.get("/search", response_model=list[SearchHit])
async def search_conversations(
    principal: PrincipalDep,
    session: SessionDep,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[SearchHit]:
    """Full-text search across all of your past conversations."""
    rows = await service.search_messages(session, principal.user, q, limit=limit)
    return [
        SearchHit(
            conversation_id=c.id,
            conversation_title=c.title,
            is_private=c.is_private,
            project=c.project,
            message_id=m.id,
            role=m.role,
            snippet=snippet,
            created_at=m.created_at,
        )
        for m, c, snippet in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> ConversationDetail:
    conversation = await _load(session, principal, conversation_id)
    messages = await service.list_messages(session, conversation, limit=limit)
    return ConversationDetail(
        conversation=ConversationOut.model_validate(conversation),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ConversationOut:
    conversation = await _load(session, principal, conversation_id)
    if body.is_private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    if body.title is not None:
        conversation.title = body.title
    if body.is_private:
        conversation.is_private = True
    if "project" in body.model_fields_set and body.project is not None:
        conversation.project = body.project or None
    await session.commit()
    return ConversationOut.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, request: Request
) -> Response:
    conversation = await _load(session, principal, conversation_id)
    manager: GenerationManager = request.app.state.generations
    manager.cancel(conversation.id, principal.user.id)
    conversation.deleted_at = datetime.now(UTC)  # tombstone (syncs later)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_reply(
    conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, request: Request
) -> dict[str, str]:
    await _load(session, principal, conversation_id)
    manager: GenerationManager = request.app.state.generations
    if not manager.cancel(conversation_id, principal.user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No reply is being generated")
    return {"status": "cancelling"}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResult,
    responses={
        200: {"description": "JSON result, or an SSE stream when `stream` is true"},
        409: {"description": "A reply is already being generated, or private not allowed"},
        429: {"description": "Too many messages"},
        503: {"description": "No AI provider could produce a reply"},
    },
)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> Any:
    received_at = time.perf_counter()
    if len(body.content) > settings.chat_max_message_chars:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Message is longer than {settings.chat_max_message_chars} characters",
        )
    conversation = await _load(session, principal, conversation_id)
    if conversation.is_private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    if not await ratelimit.allow(
        redis,
        settings,
        bucket="chat",
        identity=str(principal.user.id),
        limit=settings.chat_rate_limit_per_minute,
        window=60,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many messages. Wait a minute and try again.",
            headers={"Retry-After": "60"},
        )

    attached = []
    for document_id in dict.fromkeys(body.document_ids):
        try:
            doc = await document_service.get(session, principal.user.id, document_id)
        except document_service.DocumentNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found") from None
        if doc.is_private and not conversation.is_private:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="A private document can only be used in a private conversation.",
            )
        attached.append(doc.id)

    if not attached:
        fast = await _fast_path(
            request, session, principal, conversation, body, settings, received_at
        )
        if fast is not None:
            return fast

    manager: GenerationManager = request.app.state.generations
    try:
        active = manager.reserve(conversation.id, principal.user.id)
    except ConversationBusyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A reply is already being generated"
        ) from None

    try:
        stored_prefs = await service.get_preferences(session, principal.user)
        mode = await active_mode(session, principal.user)
        prefs = service.routing_preferences(stored_prefs)
        if mode.ai_mode:
            prefs = RoutingPreferences(mode=mode.ai_mode, cloud_order=prefs.cloud_order)  # type: ignore[arg-type]
        kind = "coding" if mode.key == "developer" else profiles.classify(body.content)
        speed = body.response_mode or stored_prefs.response_mode or "balanced"
        if speed == "deep" and kind == "chat":
            kind = "reasoning"
        prefs = profiles.preferences_for(kind, prefs, settings.ai_task_profiles)
        ai_router = request.app.state.ai_router
        if settings.ai_rank_by_speed and speed != "deep" and not conversation.is_private:
            # Fastest providers first; Deep mode keeps your chosen order (quality).
            base = [*prefs.cloud_order, *ai_router.default_cloud_order]
            order = list(dict.fromkeys(base))
            preferred = profiles.parse(settings.ai_task_profiles).get(kind, [])
            averages = await ai_speed.averages(session, principal.user.id)
            prefs = RoutingPreferences(
                mode=prefs.mode, cloud_order=ai_speed.rank(order, preferred, averages)
            )
        race = 2 if speed == "instant" and settings.ai_instant_race else 1
        memory_on = stored_prefs.memory_enabled and mode.memory
        offset = body.utc_offset_minutes
        if offset is None:
            from ultron_core.notifications import get_settings as notification_settings

            offset = (await notification_settings(session, principal.user.id)).utc_offset_minutes
        now_local = datetime.now(UTC).astimezone(timefmt.offset_zone(offset))
        h24 = stored_prefs.time_format == "24h"
        style = persona.prompt(stored_prefs.address_as, now_local, h24=h24) + SPEED_PROMPTS[speed]
        max_tokens = {
            "instant": min(settings.ai_max_output_tokens, 1024),
            "balanced": settings.ai_max_output_tokens,
            "deep": min(settings.ai_max_output_tokens * 2, 8192),
        }[speed]
        user_message, assistant_message = await service.start_exchange(
            session, conversation, body.content
        )
        history = await service.load_history(session, conversation)
        recalled = (
            await memory_service.recall(
                session,
                principal.user,
                body.content,
                private=conversation.is_private,
                limit=(
                    min(3, settings.memory_context_limit)
                    if speed == "instant"
                    else settings.memory_context_limit
                ),
                project=conversation.project,
            )
            if memory_on
            else []
        )
        excerpts = (
            await document_service.search(
                session,
                principal.user.id,
                body.content,
                document_ids=attached,
                include_private=conversation.is_private,
            )
            if attached
            else []
        )
    except BaseException:
        manager.release(conversation.id)
        raise
    active.assistant_message_id = assistant_message.id
    manager.start(
        active,
        router=request.app.state.ai_router,
        prefs=prefs,
        private=conversation.is_private,
        history=history,
        settings=settings,
        sessionmaker=request.app.state.sessionmaker,
        variant={"instant": "fast", "balanced": "default", "deep": "smart"}[speed],
        max_output_tokens=max_tokens,
        received_at=received_at,
        race=race,
        system=SYSTEM_PROMPT
        + style
        + mode.prompt()
        + memory_service.context_block(recalled)
        + document_service.context_block(excerpts),
    )

    created = {
        "user_message": MessageOut.model_validate(user_message).model_dump(mode="json"),
        "assistant_message_id": str(assistant_message.id),
        "private": conversation.is_private,
        "memories_used": len(recalled),
        "response_mode": speed,
        "document_parts_used": len(excerpts),
    }
    if body.stream:
        return StreamingResponse(
            _stream(active, created, settings.ai_stream_keepalive_seconds),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await _collect(active, created)


# Fixed rules that are clear commands even in a chat. App names count only
# when they match an app the device announced (so "open your heart" stays
# a conversation).
FAST_RULES = {"status", "timer", "alarm", "remind", "remember", "url", "workflow", "organize"}
APP_RULES = {"open", "focus", "close"}
FAST_WAIT_SECONDS = 4.0


async def _fast_path(  # type: ignore[no-untyped-def]
    request: Request, session, principal, conversation, body: MessageCreate, settings, received_at
) -> Any:
    """Clear commands typed (or spoken) in a chat run right away through the
    planner and permission system, without calling any AI model."""
    from ultron_core.tasks import planner
    from ultron_core.tasks import router as tasks_router
    from ultron_core.tasks import service as task_service

    ctx = await task_service.plan_context(session, principal, None, body.utc_offset_minutes)
    plan = planner.rule_plan(body.content, ctx)
    if plan is None or plan.rule is None:
        return None
    if plan.rule in APP_RULES:
        target = plan.steps[0].target if plan.steps else ""
        announced = {a.lower() for a in ctx.capabilities.get(target, {}).get("apps", [])}
        if str(plan.steps[0].args.get("app", "")).lower() not in announced:
            return None
    elif plan.rule not in FAST_RULES:
        return None
    prefs = await service.get_preferences(session, principal.user)
    user_message, assistant_message = await service.start_exchange(
        session, conversation, body.content
    )
    if plan.steps:
        task = await task_service.create_task(
            session, principal, plan, request=body.content, private=conversation.is_private
        )
        tasks_router._engine(request).wake()
        await tasks_router._wait(session, task.id, FAST_WAIT_SECONDS)
        text = tasks_router._task_message(
            await tasks_router._out(session, task.id), prefs.address_as
        )
    else:
        text = plan.answer or ""
    elapsed = round((time.perf_counter() - received_at) * 1000)
    assistant_message.content = text
    assistant_message.status = "complete"
    assistant_message.provider = "ultron"
    assistant_message.provider_kind = "local"
    assistant_message.model = "instant command"
    assistant_message.first_token_ms = elapsed
    assistant_message.duration_ms = elapsed
    await session.commit()
    routing = {
        "provider": "ultron",
        "kind": "local",
        "model": "instant command",
        "fallback_used": False,
        "attempts": [],
    }
    user_out = MessageOut.model_validate(user_message).model_dump(mode="json")
    assistant_out = MessageOut.model_validate(assistant_message).model_dump(mode="json")
    if not body.stream:
        return {"user_message": user_out, "assistant_message": assistant_out, "routing": routing}

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "message.created",
            {
                "user_message": user_out,
                "assistant_message_id": str(assistant_message.id),
                "private": conversation.is_private,
            },
        )
        yield _sse("provider.selected", routing)
        yield _sse("delta", {"text": text})
        yield _sse("message.completed", {"assistant_message": assistant_out, "routing": routing})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(
    active: ActiveGeneration, created: dict[str, Any], keepalive: float
) -> AsyncIterator[str]:
    try:
        yield _sse("message.created", created)
        while True:
            try:
                item = await asyncio.wait_for(active.queue.get(), timeout=keepalive)
            except TimeoutError:
                # SSE comment: keeps proxies/clients from timing out while a
                # local model loads. Clients ignore it.
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            yield _sse(*item)
    finally:
        # Client went away (or we finished): stop generating.
        if active.task is not None and not active.task.done():
            active.task.cancel()


async def _collect(active: ActiveGeneration, created: dict[str, Any]) -> Any:
    final: tuple[str, dict[str, Any]] | None = None
    try:
        while True:
            item = await active.queue.get()
            if item is None:
                break
            if item[0] in ("message.completed", "message.cancelled", "error"):
                final = item
    finally:
        if active.task is not None and not active.task.done():
            active.task.cancel()
    assert final is not None  # noqa: S101 - the task always reports an outcome
    event, payload = final
    result = {
        "user_message": created["user_message"],
        "assistant_message": payload["assistant_message"],
        "routing": payload.get("routing"),
    }
    if event == "error":
        if payload["code"] == "internal_error":
            code = status.HTTP_500_INTERNAL_SERVER_ERROR
        elif payload["code"] == "timeout":
            code = status.HTTP_504_GATEWAY_TIMEOUT
        elif payload["assistant_message"]["status"] == "failed":
            code = status.HTTP_503_SERVICE_UNAVAILABLE  # no provider could answer
        else:
            code = status.HTTP_502_BAD_GATEWAY  # provider broke off mid-reply
        return JSONResponse(
            status_code=code,
            content={
                "detail": {
                    "code": payload["code"],
                    "message": payload["message"],
                    "attempts": payload.get("attempts", []),
                },
                **result,
            },
        )
    return result
