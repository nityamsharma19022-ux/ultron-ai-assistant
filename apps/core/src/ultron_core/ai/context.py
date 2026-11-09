"""Context management: which past messages are sent to the model."""

from __future__ import annotations

from collections.abc import Sequence

from ultron_core.ai.types import ChatMessage

SYSTEM_PROMPT = """You are ULTRON, a personal AI assistant for one person, used on their \
Android phone and Windows PC.

Be helpful, accurate and concise. If you are not sure about something, say so.

You can only reply with text. You cannot run commands, open apps, send messages, \
change settings or take any other action on the user's devices or accounts, and \
nothing you write is executed. If the user asks for an action, explain how they can \
do it themselves."""


def select_context(
    history: Sequence[ChatMessage], *, char_budget: int, max_messages: int
) -> tuple[ChatMessage, ...]:
    """Keep the most recent messages that fit the budget.

    ``history`` is oldest -> newest and ends with the new user message, which
    is always kept. Older messages are dropped first; the result never starts
    with an assistant message, and consecutive same-role messages are merged
    (some providers require strict alternation).
    """
    if not history:
        return ()
    selected: list[ChatMessage] = [history[-1]]
    used = len(history[-1].content)
    for message in reversed(history[:-1]):
        if len(selected) >= max_messages or used + len(message.content) > char_budget:
            break
        selected.append(message)
        used += len(message.content)
    selected.reverse()

    while len(selected) > 1 and selected[0].role != "user":
        selected.pop(0)

    merged: list[ChatMessage] = []
    for message in selected:
        if merged and merged[-1].role == message.role:
            merged[-1] = ChatMessage(message.role, merged[-1].content + "\n\n" + message.content)
        else:
            merged.append(message)
    return tuple(merged)
