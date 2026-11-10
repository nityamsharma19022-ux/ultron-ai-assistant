"""Time format, form of address, response mode; reply timing

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_ai_preferences",
        sa.Column("time_format", sa.String(4), server_default="12h", nullable=False),
    )
    op.add_column(
        "user_ai_preferences",
        sa.Column("address_as", sa.String(40), server_default="Sir", nullable=False),
    )
    op.add_column(
        "user_ai_preferences",
        sa.Column("response_mode", sa.String(10), server_default="balanced", nullable=False),
    )
    op.add_column("messages", sa.Column("first_token_ms", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "duration_ms")
    op.drop_column("messages", "first_token_ms")
    op.drop_column("user_ai_preferences", "response_mode")
    op.drop_column("user_ai_preferences", "address_as")
    op.drop_column("user_ai_preferences", "time_format")
