"""Tables: auth (Phase 1) and chat + AI preferences (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ultron_core.db.base import Base, IdMixin, TimestampMixin

DEVICE_PLATFORMS = ("android", "windows", "other")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    devices: Mapped[list[Device]] = relationship(back_populates="user")

    # eager_defaults: read server-set columns (updated_at) back immediately.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class Device(IdMixin, TimestampMixin, Base):
    """A paired client (an Android phone, a Windows PC, ...)."""

    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    user: Mapped[User] = relationship(back_populates="devices")

    # eager_defaults: read server-set columns (updated_at) back immediately.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class RefreshToken(IdMixin, Base):
    """Opaque refresh token (only its SHA-256 hash is stored).

    Tokens rotate on every use. All tokens from one login share a
    ``family_id``; presenting an already-used token revokes the whole family
    (reuse detection).
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Phase 2: chat ------------------------------------------------------------

MESSAGE_ROLES = ("user", "assistant")
# streaming: being generated | complete | incomplete: provider failed mid-reply
# failed: no reply produced | cancelled: stopped by the user
MESSAGE_STATUSES = ("streaming", "complete", "incomplete", "failed", "cancelled")


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200))
    # Private conversations only ever use local AI and are only stored by a
    # local backend. Once private, always private.
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    # eager_defaults: read server-set columns (updated_at) back immediately.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        CheckConstraint(
            "status IN ('streaming', 'complete', 'incomplete', 'failed', 'cancelled')",
            name="status",
        ),
        Index("ix_messages_conversation_seq", "conversation_id", "seq"),
    )

    # Server-assigned order (also the basis for the future sync change feed).
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_kind: Mapped[str | None] = mapped_column(String(10))
    model: Mapped[str | None] = mapped_column(String(200))
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    # eager_defaults: read server-set columns (updated_at) back immediately.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class UserAIPreferences(Base):
    __tablename__ = "user_ai_preferences"
    __table_args__ = (CheckConstraint("mode IN ('auto', 'cloud_only', 'local_only')", name="mode"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    cloud_order: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    private_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    # eager_defaults: read server-set columns (updated_at) back immediately.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012
