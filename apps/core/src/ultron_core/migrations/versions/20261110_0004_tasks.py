"""Tasks, steps, permission grants, automation state, agents, reminders, schedules

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
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


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    task_statuses = (
        "'planning', 'awaiting_approval', 'queued', 'running', 'paused', "
        "'completed', 'failed', 'cancelled'"
    )
    step_statuses = (
        "'pending', 'awaiting_approval', 'ready', 'running', 'succeeded', "
        "'failed', 'cancelled', 'skipped'"
    )
    op.create_table(
        "tasks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("device_id", UUID, nullable=True),
        sa.Column("schedule_id", UUID, nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("plan_source", sa.String(20), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("started_at", True),
        _ts("finished_at", True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"status IN ({task_statuses})", name=op.f("ck_tasks_status")),
        _fk("tasks", "user_id", "users", "CASCADE"),
        _fk("tasks", "device_id", "devices", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"])

    op.create_table(
        "task_steps",
        sa.Column("id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(60), nullable=False),
        sa.Column("args", JSONB, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("target", sa.String(10), nullable=False),
        sa.Column("risk", sa.String(1), nullable=False),
        sa.Column("scope", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("progress", sa.String(300), nullable=True),
        sa.Column("assigned_device_id", UUID, nullable=True),
        _ts("not_before", True),
        _ts("started_at", True),
        _ts("finished_at", True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"status IN ({step_statuses})", name=op.f("ck_task_steps_status")),
        sa.CheckConstraint("risk IN ('A', 'B', 'C')", name=op.f("ck_task_steps_risk")),
        sa.CheckConstraint(
            "target IN ('core', 'windows', 'android')", name=op.f("ck_task_steps_target")
        ),
        _fk("task_steps", "task_id", "tasks", "CASCADE"),
        _fk("task_steps", "assigned_device_id", "devices", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_steps")),
    )
    op.create_index(op.f("ix_task_steps_task_id"), "task_steps", ["task_id"])
    op.create_index("ix_task_steps_ready", "task_steps", ["target", "status"])

    op.create_table(
        "permission_grants",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("scope", sa.String(60), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _ts("expires_at", True),
        _ts("created_at"),
        _ts("updated_at"),
        _fk("permission_grants", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "scope", name=op.f("pk_permission_grants")),
    )

    op.create_table(
        "automation_state",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _ts("stopped_at", True),
        _ts("updated_at"),
        _fk("automation_state", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_automation_state")),
    )

    op.create_table(
        "agents",
        sa.Column("device_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("target", sa.String(10), nullable=False),
        sa.Column("tools", JSONB, nullable=False),
        sa.Column("capabilities", JSONB, nullable=False),
        sa.Column("agent_version", sa.String(40), nullable=True),
        _ts("last_seen_at"),
        _fk("agents", "device_id", "devices", "CASCADE"),
        _fk("agents", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("device_id", name=op.f("pk_agents")),
    )
    op.create_index(op.f("ix_agents_user_id"), "agents", ["user_id"])

    op.create_table(
        "reminders",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        _ts("due_at"),
        sa.Column("done", sa.Boolean(), nullable=False),
        _ts("delivered_at", True),
        sa.Column("task_id", UUID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _fk("reminders", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminders")),
    )
    op.create_index(op.f("ix_reminders_user_id"), "reminders", ["user_id"])

    op.create_table(
        "schedules",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("every", sa.String(10), nullable=False),
        _ts("next_run_at"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_task_id", UUID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "every IN ('hourly', 'daily', 'weekly')", name=op.f("ck_schedules_every")
        ),
        _fk("schedules", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
    )
    op.create_index(op.f("ix_schedules_user_id"), "schedules", ["user_id"])


def downgrade() -> None:
    for index, table in (
        ("ix_schedules_user_id", "schedules"),
        ("ix_reminders_user_id", "reminders"),
        ("ix_agents_user_id", "agents"),
    ):
        op.drop_index(op.f(index), table_name=table)
    op.drop_table("schedules")
    op.drop_table("reminders")
    op.drop_table("agents")
    op.drop_table("automation_state")
    op.drop_table("permission_grants")
    op.drop_index("ix_task_steps_ready", table_name="task_steps")
    op.drop_index(op.f("ix_task_steps_task_id"), table_name="task_steps")
    op.drop_table("task_steps")
    op.drop_index("ix_tasks_user_status", table_name="tasks")
    op.drop_table("tasks")
