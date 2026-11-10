"""Tables: auth (Phase 1), chat + AI preferences (Phase 2), memory and activity
(Stage 2), tasks and permissions (Stage 3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
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
    # Saved memories are added to the AI's context (Stage 2).
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Operating mode (built-in key or a custom mode's key).
    active_mode: Mapped[str] = mapped_column(
        String(40), nullable=False, default="normal", server_default="normal"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    # eager_defaults: read server-set columns (updated_at) back immediately.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


# --- Stage 2: memory and activity ---------------------------------------------

MEMORY_KINDS = ("preference", "fact", "project", "note")
MEMORY_SOURCES = ("user", "chat", "task")


class Memory(IdMixin, TimestampMixin, Base):
    """Something the user wants ULTRON to remember. Always user-controlled:
    created by the user (or a task they ran), editable and deletable."""

    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint("kind IN ('preference', 'fact', 'project', 'note')", name="kind"),
        CheckConstraint("source IN ('user', 'chat', 'task')", name="source"),
        Index("ix_memories_search", "search", postgresql_using="gin"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="note")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # Private memories are only used in private (local-AI-only) conversations.
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class ActivityEvent(Base):
    """User-visible history of what ULTRON did (audit log). Never holds secrets."""

    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_events_user_seq", "user_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- Stage 3: tasks, permissions, agents ---------------------------------------

TASK_STATUSES = (
    "planning",
    "awaiting_approval",
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
)
STEP_STATUSES = (
    "pending",
    "awaiting_approval",
    "ready",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Task(IdMixin, TimestampMixin, Base):
    """Something the user asked ULTRON to do, planned into steps."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status"),
        Index("ix_tasks_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # rules | ai | manual | schedule
    plan_source: Mapped[str] = mapped_column(String(20), nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task", order_by="TaskStep.idx", cascade="all, delete-orphan"
    )

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class TaskStep(IdMixin, TimestampMixin, Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        CheckConstraint(_in("status", STEP_STATUSES), name="status"),
        CheckConstraint("risk IN ('A', 'B', 'C')", name="risk"),
        CheckConstraint("target IN ('core', 'windows', 'android')", name="target"),
        Index("ix_task_steps_ready", "target", "status"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(60), nullable=False)
    args: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    target: Mapped[str] = mapped_column(String(10), nullable=False)
    risk: Mapped[str] = mapped_column(String(1), nullable=False)
    scope: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[str | None] = mapped_column(String(300))
    assigned_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    task: Mapped[Task] = relationship(back_populates="steps")

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class PermissionGrant(Base):
    """The user allows a routine (class A) action scope to run without asking."""

    __tablename__ = "permission_grants"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(60), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AutomationState(Base):
    """Master switch and emergency stop for automatic task execution."""

    __tablename__ = "automation_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Autonomy level 0-5 per area ("core", "pc", "phone"); missing = 3.
    levels: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentInfo(Base):
    """A device running a ULTRON agent (Windows agent, Android app) and the
    tools it says it can run."""

    __tablename__ = "agents"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target: Mapped[str] = mapped_column(String(10), nullable=False)
    tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Non-secret description of the agent's local setup (allowed folders,
    # app names, workflow names) so the planner can use real names.
    capabilities: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    agent_version: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Reminder(IdMixin, TimestampMixin, Base):
    __tablename__ = "reminders"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Schedule(IdMixin, TimestampMixin, Base):
    """A recurring task: a saved plan run on a fixed rhythm."""

    __tablename__ = "schedules"
    __table_args__ = (CheckConstraint("every IN ('hourly', 'daily', 'weekly')", name="every"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    every: Mapped[str] = mapped_column(String(10), nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# --- Stage 6: documents -------------------------------------------------------


class Document(IdMixin, TimestampMixin, Base):
    """An uploaded file whose text ULTRON can search and use."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_user_sha", "user_id", "sha256", unique=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf, docx, text, sheet
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer)
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Private documents are only used with local AI (private conversations).
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_document_chunks_search", "search", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )


# --- Round 2: operating modes, notifications ----------------------------------


class AssistantMode(IdMixin, TimestampMixin, Base):
    """A custom operating mode (built-in modes live in code)."""

    __tablename__ = "assistant_modes"
    __table_args__ = (Index("ix_assistant_modes_user_key", "user_id", "key", unique=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_mode: Mapped[str | None] = mapped_column(String(20))
    memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tool_areas: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quiet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


NOTIFICATION_PRIORITIES = ("low", "normal", "high", "urgent")


class Notification(IdMixin, Base):
    """Something ULTRON wants the user to know (shown on every device)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="priority"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_dedupe", "user_id", "dedupe_key", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Rules use this so the same situation is only reported once.
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Quiet hours in the user's local time, "HH:MM"; None = off.
    quiet_start: Mapped[str | None] = mapped_column(String(5))
    quiet_end: Mapped[str | None] = mapped_column(String(5))
    utc_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Lowest priority that is announced (shown/pushed) outside quiet hours.
    min_priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    daily_briefing: Mapped[str | None] = mapped_column(String(5))  # "HH:MM" local
    last_briefing_on: Mapped[str | None] = mapped_column(String(10))  # local date
