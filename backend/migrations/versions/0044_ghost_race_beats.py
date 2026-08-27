"""Phase 4 ghost racing — persist beat events when a racer beats a ghost.

Revision ID: 0044_ghost_race_beats
Revises: 0043_beat_notification_consent
Create Date: 2026-08-27 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_ghost_race_beats"
down_revision: Union[str, None] = "0043_beat_notification_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ghost_race_beats",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("racer_user_id", sa.String(), nullable=False),
        sa.Column("racer_action_run_id", sa.String(), nullable=False),
        sa.Column("ghost_action_run_id", sa.String(), nullable=False),
        sa.Column("ghost_owner_user_id", sa.String(), nullable=True),
        sa.Column(
            "ghost_owner_beat_notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("racer_containment_seconds", sa.Integer(), nullable=False),
        sa.Column("ghost_containment_seconds", sa.Integer(), nullable=False),
        sa.Column("beat_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ghost_action_run_id"], ["action_runs.id"]),
        sa.ForeignKeyConstraint(["ghost_owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["racer_action_run_id"], ["action_runs.id"]),
        sa.ForeignKeyConstraint(["racer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("racer_action_run_id", name="uq_ghost_race_beats_racer_action_run"),
    )
    op.create_index(
        "ix_ghost_race_beats_racer_user_id",
        "ghost_race_beats",
        ["racer_user_id"],
    )
    op.create_index(
        "ix_ghost_race_beats_ghost_action_run_id",
        "ghost_race_beats",
        ["ghost_action_run_id"],
    )
    op.create_index(
        "ix_ghost_race_beats_ghost_owner_user_id",
        "ghost_race_beats",
        ["ghost_owner_user_id"],
    )
    op.create_index(
        "ix_ghost_race_beats_beat_at",
        "ghost_race_beats",
        ["beat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ghost_race_beats_beat_at", table_name="ghost_race_beats")
    op.drop_index("ix_ghost_race_beats_ghost_owner_user_id", table_name="ghost_race_beats")
    op.drop_index("ix_ghost_race_beats_ghost_action_run_id", table_name="ghost_race_beats")
    op.drop_index("ix_ghost_race_beats_racer_user_id", table_name="ghost_race_beats")
    op.drop_table("ghost_race_beats")
