"""Autonomy levels, operating modes, notifications

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def upgrade() -> None:
    op.add_column(
        "automation_state", sa.Column("levels", JSONB, server_default="{}", nullable=False)
    )
    op.add_column(
        "user_ai_preferences",
        sa.Column("active_mode", sa.String(40), server_default="normal", nullable=False),
    )
    op.create_table(
        "assistant_modes",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("personality", sa.Text(), nullable=False),
        sa.Column("ai_mode", sa.String(20), nullable=True),
        sa.Column("memory", sa.Boolean(), nullable=False),
        sa.Column("tool_areas", JSONB, nullable=False),
        sa.Column("quiet", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_assistant_modes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_modes")),
    )
    op.create_index(
        "ix_assistant_modes_user_key", "assistant_modes", ["user_id", "key"], unique=True
    )
    op.create_table(
        "notifications",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("task_id", UUID, nullable=True),
        sa.Column("dedupe_key", sa.String(120), nullable=True),
        _ts("read_at", True),
        _ts("created_at"),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name=op.f("ck_notifications_priority"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])
    op.create_index(
        "ix_notifications_dedupe", "notifications", ["user_id", "dedupe_key"], unique=True
    )
    op.create_table(
        "notification_settings",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("quiet_start", sa.String(5), nullable=True),
        sa.Column("quiet_end", sa.String(5), nullable=True),
        sa.Column("utc_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("min_priority", sa.String(10), nullable=False),
        sa.Column("daily_briefing", sa.String(5), nullable=True),
        sa.Column("last_briefing_on", sa.String(10), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_settings")),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
    op.drop_index("ix_notifications_dedupe", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_assistant_modes_user_key", table_name="assistant_modes")
    op.drop_table("assistant_modes")
    op.drop_column("user_ai_preferences", "active_mode")
    op.drop_column("automation_state", "levels")
