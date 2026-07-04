"""Add arena_events table + arena_matches.event_id (Live Breach Events Phase 4)

Revision ID: 0027_arena_events
Revises: 0026_arena_stats_index
Create Date: 2026-07-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027_arena_events"
down_revision: Union[str, None] = "0026_arena_stats_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Reuses the arena_matches.difficulty enum type as-is (create_type=False,
    # no .create() call — it already exists as of migration 0023). Both
    # columns share the identical easy/medium/hard domain, and an event's
    # difficulty is copied verbatim onto every ArenaMatch paired under it.
    arena_match_difficulty = postgresql.ENUM(
        "easy", "medium", "hard", name="arena_match_difficulty", create_type=False
    )

    arena_event_status = postgresql.ENUM(
        "scheduled", "live", "completed", "cancelled", name="arena_event_status", create_type=False
    )
    arena_event_status.create(bind, checkfirst=True)

    op.create_table(
        "arena_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scenario_id", sa.String(), nullable=True),
        sa.Column("archetype_key", sa.String(length=100), nullable=False),
        sa.Column("difficulty", arena_match_difficulty, nullable=False, server_default="medium"),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("status", arena_event_status, nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_arena_events_starts_at", "arena_events", ["starts_at"])
    op.create_index("ix_arena_events_status", "arena_events", ["status"])

    op.add_column(
        "arena_matches",
        sa.Column("event_id", sa.String(), nullable=True),
    )
    op.create_index("ix_arena_matches_event_id", "arena_matches", ["event_id"])
    op.create_foreign_key(
        "fk_arena_matches_event_id",
        "arena_matches",
        "arena_events",
        ["event_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_arena_matches_event_id", "arena_matches", type_="foreignkey")
    op.drop_index("ix_arena_matches_event_id", table_name="arena_matches")
    op.drop_column("arena_matches", "event_id")

    op.drop_index("ix_arena_events_status", table_name="arena_events")
    op.drop_index("ix_arena_events_starts_at", table_name="arena_events")
    op.drop_table("arena_events")

    bind = op.get_bind()
    postgresql.ENUM(name="arena_event_status").drop(bind, checkfirst=True)
    # arena_match_difficulty is NOT dropped here — arena_matches.difficulty
    # (added in migration 0023) still depends on it.
