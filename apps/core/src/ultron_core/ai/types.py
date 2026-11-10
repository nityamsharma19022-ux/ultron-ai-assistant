"""Provider-independent types shared by every AI adapter and the router."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

Role = Literal["system", "user", "assistant"]


class ProviderKind(StrEnum):
    CLOUD = "cloud"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """What every provider receives. Text in, text out: no tools are ever sent,
    so a model can never trigger an action (see SECURITY.md)."""

    messages: tuple[ChatMessage, ...]
    system: str
    max_output_tokens: int = 2048
    # "fast", "default" or "smart": routers like FreeLLMAPI pick a model tier.
    variant: str = "default"


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class StreamEnd:
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None


StreamEvent = TextDelta | StreamEnd


@dataclass(slots=True)
class Availability:
    available: bool
    reason: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
