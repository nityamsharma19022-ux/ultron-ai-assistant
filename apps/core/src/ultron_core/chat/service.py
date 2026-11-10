"""Conversation and message persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.ai.router import RoutingPreferences
from ultron_core.ai.types import ChatMessage
from ultron_core.db.models import Conversation, Message, User, UserAIPreferences

HISTORY_LOAD_LIMIT = 500


class ConversationNotFoundError(Exception):
    pass


async def get_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.deleted_at:
        raise ConversationNotFoundError
    return conversation


async def list_conversations(
    session: AsyncSession, user: User, *, limit: int, offset: int
) -> list[Conversation]:
    result = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def search_messages(
    session: AsyncSession, user: User, query: str, *, limit: int
) -> list[tuple[Message, Conversation, str]]:
    """Past messages matching ``query`` (full-text, best matches first)."""
    from ultron_core.memory.service import TS_CONFIG, tsquery_text

    tsq = tsquery_text(query)
    if tsq is None:
        return []
    q = func.to_tsquery(TS_CONFIG, tsq)
    snippet = func.ts_headline(
        TS_CONFIG,
        Message.content,
        q,
        "MaxWords=30, MinWords=10, MaxFragments=2, StartSel=«, StopSel=»",
    )
    rows = await session.execute(
        select(Message, Conversation, snippet)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
            Message.search.op("@@")(q),
        )
        .order_by(func.ts_rank(Message.search, q).desc(), Message.seq.desc())
        .limit(limit)
    )
    return [(m, c, s) for m, c, s in rows.all()]


async def list_messages(
    session: AsyncSession, conversation: Conversation, *, limit: int
) -> list[Message]:
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    return list(reversed(list(result)))


async def load_history(session: AsyncSession, conversation: Conversation) -> list[ChatMessage]:
    """Messages usable as model context: only completed ones, oldest first."""
    rows = await list_messages(session, conversation, limit=HISTORY_LOAD_LIMIT)
    return [
        ChatMessage(role=m.role, content=m.content)  # type: ignore[arg-type]
        for m in rows
        if m.status == "complete" and m.content
    ]


async def get_preferences(session: AsyncSession, user: User) -> UserAIPreferences:
    prefs = await session.get(UserAIPreferences, user.id)
    if prefs is None:
        prefs = UserAIPreferences(
            user_id=user.id,
            mode="auto",
            cloud_order=[],
            private_by_default=False,
            memory_enabled=True,
            memory_saving_paused=False,
            active_mode="normal",
        )
    return prefs


def routing_preferences(prefs: UserAIPreferences) -> RoutingPreferences:
    return RoutingPreferences(mode=prefs.mode, cloud_order=tuple(prefs.cloud_order))  # type: ignore[arg-type]


async def start_exchange(
    session: AsyncSession, conversation: Conversation, content: str
) -> tuple[Message, Message]:
    """Store the user's message and an empty assistant placeholder."""
    user_message = Message(
        conversation_id=conversation.id, role="user", content=content, status="complete"
    )
    session.add(user_message)
    await session.flush()
    assistant_message = Message(
        conversation_id=conversation.id, role="assistant", content="", status="streaming"
    )
    session.add(assistant_message)
    if not conversation.title:
        conversation.title = content[:60] + ("…" if len(content) > 60 else "")
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    return user_message, assistant_message


async def mark_stale_generations_failed(session: AsyncSession, older_than_minutes: int = 10) -> int:
    """Replies left 'streaming' by a crash or restart are marked failed."""
    result = await session.execute(
        update(Message)
        .where(
            Message.status == "streaming",
            Message.updated_at < func.now() - func.make_interval(0, 0, 0, 0, 0, older_than_minutes),
        )
        .values(status="failed", error_code="interrupted", version=Message.version + 1)
    )
    await session.commit()
    return result.rowcount or 0
