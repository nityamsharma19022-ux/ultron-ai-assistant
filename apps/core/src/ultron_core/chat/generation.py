"""Runs one assistant reply as its own task.

The task streams events into a queue that the HTTP response reads. Running
the reply in a separate task makes cancellation simple and reliable:

- the cancel endpoint cancels the task;
- if the client disconnects, the response's cleanup cancels the task.

Whatever happens, the task records the final state of the assistant message
(complete / incomplete / failed / cancelled) before it ends.

One reply at a time per conversation; cancellation works within this server
process (the local backend runs a single process).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ultron_core.ai.context import SYSTEM_PROMPT, select_context
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.router import (
    AIRouter,
    Completed,
    MidStreamError,
    ProviderSelected,
    RouteInfo,
    RoutingError,
    RoutingPreferences,
)
from ultron_core.ai.types import ChatMessage, ChatRequest, TextDelta
from ultron_core.chat.schemas import MessageOut
from ultron_core.config import Settings
from ultron_core.db.models import Message
from ultron_core.logging_setup import get_logger

log = get_logger("ultron.chat.generation")

QueueItem = tuple[str, dict[str, Any]] | None


@dataclass
class ActiveGeneration:
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    assistant_message_id: uuid.UUID | None = None
    task: asyncio.Task[None] | None = None
    queue: asyncio.Queue[QueueItem] = field(default_factory=asyncio.Queue)


class ConversationBusyError(Exception):
    pass


class GenerationManager:
    def __init__(self) -> None:
        self._active: dict[uuid.UUID, ActiveGeneration] = {}

    def reserve(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> ActiveGeneration:
        """Claim the conversation (synchronous, so there is no race)."""
        if conversation_id in self._active:
            raise ConversationBusyError
        active = ActiveGeneration(conversation_id=conversation_id, user_id=user_id)
        self._active[conversation_id] = active
        return active

    def release(self, conversation_id: uuid.UUID) -> None:
        self._active.pop(conversation_id, None)

    def get(self, conversation_id: uuid.UUID) -> ActiveGeneration | None:
        return self._active.get(conversation_id)

    def cancel(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        active = self._active.get(conversation_id)
        if active is None or active.user_id != user_id or active.task is None:
            return False
        if active.task.done():
            return False
        active.task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = [a.task for a in self._active.values() if a.task and not a.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def start(
        self,
        active: ActiveGeneration,
        *,
        router: AIRouter,
        prefs: RoutingPreferences,
        private: bool,
        history: list[ChatMessage],
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        active.task = asyncio.create_task(
            self._run(active, router, prefs, private, history, settings, sessionmaker),
            name=f"ultron-generation-{active.conversation_id}",
        )

    async def _run(
        self,
        active: ActiveGeneration,
        router: AIRouter,
        prefs: RoutingPreferences,
        private: bool,
        history: list[ChatMessage],
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        def build_request(provider: ChatProvider) -> ChatRequest:
            return ChatRequest(
                messages=select_context(
                    history,
                    char_budget=provider.context_char_budget,
                    max_messages=settings.ai_context_max_messages,
                ),
                system=SYSTEM_PROMPT,
                max_output_tokens=settings.ai_max_output_tokens,
            )

        parts: list[str] = []
        route: RouteInfo | None = None
        outcome: dict[str, Any] = {"status": "failed", "error": None, "end": None}
        try:
            async with contextlib.aclosing(
                router.stream(build_request, prefs, private=private)
            ) as events:
                async for event in events:
                    if isinstance(event, ProviderSelected):
                        route = event.route
                        await active.queue.put(("provider.selected", route.as_dict()))
                    elif isinstance(event, TextDelta):
                        parts.append(event.text)
                        await active.queue.put(("delta", {"text": event.text}))
                    elif isinstance(event, Completed):
                        route = event.route
                        outcome = {"status": "complete", "error": None, "end": event.end}
        except RoutingError as exc:
            outcome = {
                "status": "failed",
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "attempts": [a.as_dict() for a in exc.attempts],
                },
                "end": None,
            }
        except MidStreamError as exc:
            route = exc.route
            outcome = {
                "status": "incomplete",
                "error": {
                    "code": exc.error.code,
                    "message": "The reply was interrupted: " + exc.error.message,
                    "attempts": [a.as_dict() for a in exc.route.attempts],
                },
                "end": None,
            }
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            outcome = {"status": "cancelled", "error": None, "end": None}
        except Exception:
            log.exception("chat.generation_crashed")
            outcome = {
                "status": "failed",
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong.",
                    "attempts": [],
                },
                "end": None,
            }

        # Record the result even if we are being cancelled a second time.
        finalize = asyncio.ensure_future(
            self._finalize(active, sessionmaker, "".join(parts), route, outcome)
        )
        try:
            await asyncio.shield(finalize)
        except asyncio.CancelledError:
            await finalize
        finally:
            self.release(active.conversation_id)
            await active.queue.put(None)

    async def _finalize(
        self,
        active: ActiveGeneration,
        sessionmaker: async_sessionmaker[AsyncSession],
        text: str,
        route: RouteInfo | None,
        outcome: dict[str, Any],
    ) -> None:
        error = outcome["error"]
        end = outcome["end"]
        async with sessionmaker() as session:
            message = await session.get(Message, active.assistant_message_id)
            if message is None:  # pragma: no cover - deleted mid-reply
                return
            message.content = text
            message.status = outcome["status"]
            message.error_code = error["code"] if error else None
            if route is not None:
                message.provider = route.provider
                message.provider_kind = route.kind.value
                message.model = route.model
                message.fallback_used = route.fallback_used
            if end is not None:
                message.input_tokens = end.input_tokens
                message.output_tokens = end.output_tokens
            await session.commit()
            payload: dict[str, Any] = {
                "assistant_message": MessageOut.model_validate(message).model_dump(mode="json"),
                "routing": route.as_dict() if route else None,
            }
        log.info(
            "chat.reply_finished",
            status=outcome["status"],
            provider=route.provider if route else None,
            kind=route.kind.value if route else None,
            error_code=error["code"] if error else None,
            chars=len(text),
        )
        if outcome["status"] == "complete":
            await active.queue.put(("message.completed", payload))
        elif outcome["status"] == "cancelled":
            await active.queue.put(("message.cancelled", payload))
        else:
            await active.queue.put(("error", {**error, **payload}))
