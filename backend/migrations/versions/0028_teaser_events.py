"""Add teaser_events table (Phase 1 — no-auth landing teaser funnel log)

Revision ID: 0028_teaser_events
Revises: 0027_arena_events
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0028_teaser_events"
down_revision: Union[str, None] = "0027_arena_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    teaser_event_type = postgresql.ENUM(
        "teaser_started", "teaser_decided", "teaser_completed", "signup_from_teaser",
        name="teaser_event_type",
    )
    teaser_event_type.create(bind, checkfirst=True)

    op.create_table(
        "teaser_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", teaser_event_type, nullable=False),
        sa.Column("token_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_key", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teaser_events_event_type", "teaser_events", ["event_type"])
    op.create_index("ix_teaser_events_token_id", "teaser_events", ["token_id"])
    op.create_index("ix_teaser_events_created_at", "teaser_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_teaser_events_created_at", table_name="teaser_events")
    op.drop_index("ix_teaser_events_token_id", table_name="teaser_events")
    op.drop_index("ix_teaser_events_event_type", table_name="teaser_events")
    op.drop_table("teaser_events")

    bind = op.get_bind()
    postgresql.ENUM(name="teaser_event_type").drop(bind, checkfirst=True)
