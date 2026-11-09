"""Chat endpoints (/api/v1/conversations...)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from ultron_core import ratelimit
from ultron_core.chat import service
from ultron_core.chat.generation import ActiveGeneration, ConversationBusyError, GenerationManager
from ultron_core.chat.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageCreate,
    MessageOut,
    SendMessageResult,
)
from ultron_core.db.models import Conversation
from ultron_core.deps import PrincipalDep, RedisDep, SessionDep, SettingsDep

router = APIRouter(prefix="/conversations", tags=["chat"])

PRIVATE_NOT_ALLOWED = (
    "Private conversations are only available on a local ULTRON backend using a "
    "local database, so that their data stays on your own machine."
)


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
    conversation = Conversation(user_id=principal.user.id, title=body.title, is_private=is_private)
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

    manager: GenerationManager = request.app.state.generations
    try:
        active = manager.reserve(conversation.id, principal.user.id)
    except ConversationBusyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A reply is already being generated"
        ) from None

    try:
        prefs = service.routing_preferences(await service.get_preferences(session, principal.user))
        user_message, assistant_message = await service.start_exchange(
            session, conversation, body.content
        )
        history = await service.load_history(session, conversation)
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
    )

    created = {
        "user_message": MessageOut.model_validate(user_message).model_dump(mode="json"),
        "assistant_message_id": str(assistant_message.id),
        "private": conversation.is_private,
    }
    if body.stream:
        return StreamingResponse(
            _stream(active, created),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await _collect(active, created)


async def _stream(active: ActiveGeneration, created: dict[str, Any]) -> AsyncIterator[str]:
    try:
        yield _sse("message.created", created)
        while True:
            item = await active.queue.get()
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
