"""Memory projects, memory-saving pause, conversation search

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("project", sa.String(80), nullable=True))
    op.add_column("memories", sa.Column("project", sa.String(80), nullable=True))
    op.create_index("ix_memories_user_project", "memories", ["user_id", "project"])
    op.add_column(
        "user_ai_preferences",
        sa.Column("memory_saving_paused", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_messages_search", "messages", ["search"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_messages_search", table_name="messages")
    op.drop_column("messages", "search")
    op.drop_column("user_ai_preferences", "memory_saving_paused")
    op.drop_index("ix_memories_user_project", table_name="memories")
    op.drop_column("memories", "project")
    op.drop_column("conversations", "project")
