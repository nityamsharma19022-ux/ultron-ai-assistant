"""Validated request/response models for the chat and AI APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Hard upper bound; the configured ULTRON_CHAT_MAX_MESSAGE_CHARS is checked too.
ABSOLUTE_MAX_MESSAGE_CHARS = 100_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value.strip()


class ConversationCreate(_Strict):
    title: str | None = Field(default=None, max_length=200)
    # None = use the user's "private by default" preference.
    is_private: bool | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return (_clean_text(v) or None) if v is not None else None


class ConversationUpdate(_Strict):
    title: str | None = Field(default=None, max_length=200)
    # Privacy can be switched on but never off.
    is_private: Literal[True] | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return (_clean_text(v) or None) if v is not None else None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    is_private: bool
    created_at: datetime
    updated_at: datetime


class MessageCreate(_Strict):
    content: str = Field(min_length=1, max_length=ABSOLUTE_MAX_MESSAGE_CHARS)
    stream: bool = False
    # Documents to answer from (their relevant parts are given to the AI).
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)

    @field_validator("content")
    @classmethod
    def _content(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("must not be empty")
        return v


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    status: str
    provider: str | None
    provider_kind: str | None
    model: str | None
    fallback_used: bool
    error_code: str | None
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]


class SendMessageResult(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    routing: dict[str, object] | None


class PreferencesIn(_Strict):
    mode: Literal["auto", "cloud_only", "local_only"] = "auto"
    cloud_order: list[str] = Field(default_factory=list, max_length=20)
    private_by_default: bool = False
    # None keeps the current value (older apps don't send it).
    memory_enabled: bool | None = None


class PreferencesOut(BaseModel):
    mode: str
    cloud_order: list[str]
    private_by_default: bool
    memory_enabled: bool
    available_cloud_providers: list[str]


class ProviderStatus(BaseModel):
    name: str
    kind: str
    model: str | None
    configured: bool
    available: bool
    status: str
    reason: str | None = None
    cooldown_remaining_seconds: int | None = None
    # Local providers: whether the model is already in memory (None = unknown).
    model_loaded: bool | None = None


class AIStatus(BaseModel):
    mode: str
    cloud_available: bool
    local_ai_available: bool
    private_conversations_supported: bool
    providers: list[ProviderStatus]


class WarmupResult(BaseModel):
    status: Literal["ready"]
    provider: str
    model: str | None
    already_loaded: bool
    seconds: float
