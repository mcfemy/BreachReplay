"""Add action_runs table (Phase 2 — action console core loop)

Revision ID: 0029_action_runs
Revises: 0028_teaser_events
Create Date: 2026-07-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0029_action_runs"
down_revision: Union[str, None] = "0028_teaser_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    action_run_mode = postgresql.ENUM(
        "daily", "scenario", "teaser", name="action_run_mode",
    )
    action_run_mode.create(bind, checkfirst=True)

    action_run_outcome = postgresql.ENUM(
        "win", "loss", "partial", name="action_run_outcome",
    )
    action_run_outcome.create(bind, checkfirst=True)

    op.create_table(
        "action_runs",
        sa.Column("id", sa.String(), nullable=False),
        # Nullable — a teaser-mode run has no authenticated user yet (the
        # same "no account required" model as TeaserEvent.user_id;
        # migration 0028).
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("scenario_id", sa.String(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("mode", action_run_mode, nullable=False),
        # Timestamped verb log — the single source of truth for this run's
        # replay. This IS the Phase 4 ghost-racing replay format and the
        # format the existing SessionReplayScrubber will read.
        sa.Column("action_log", JSONB().with_variant(sa.JSON, "sqlite"), nullable=False, server_default="[]"),
        sa.Column("score_breakdown", JSONB().with_variant(sa.JSON, "sqlite"), nullable=False, server_default="{}"),
        # A plain sortable column, deliberately separate from
        # score_breakdown (JSONB): leaderboard queries (Daily Breach, Item
        # 4) need to ORDER BY a real indexed integer column — sorting on a
        # JSONB path is neither indexable the same way nor portable across
        # the SQLite test dialect.
        sa.Column("total_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("outcome", action_run_outcome, nullable=False),
        # CURRENT_TIMESTAMP (not Postgres-only NOW(), the convention used by
        # 0027/0028) so this migration is also exercisable against SQLite —
        # see tests/test_action_runs_migration.py's round-trip test. Both
        # are ANSI SQL and Postgres treats them identically.
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_runs_user_id", "action_runs", ["user_id"])
    op.create_index("ix_action_runs_scenario_id", "action_runs", ["scenario_id"])
    op.create_index("ix_action_runs_mode", "action_runs", ["mode"])
    op.create_index("ix_action_runs_created_at", "action_runs", ["created_at"])
    op.create_index("ix_action_runs_total_score", "action_runs", ["total_score"])


def downgrade() -> None:
    op.drop_index("ix_action_runs_total_score", table_name="action_runs")
    op.drop_index("ix_action_runs_created_at", table_name="action_runs")
    op.drop_index("ix_action_runs_mode", table_name="action_runs")
    op.drop_index("ix_action_runs_scenario_id", table_name="action_runs")
    op.drop_index("ix_action_runs_user_id", table_name="action_runs")
    op.drop_table("action_runs")

    bind = op.get_bind()
    postgresql.ENUM(name="action_run_outcome").drop(bind, checkfirst=True)
    postgresql.ENUM(name="action_run_mode").drop(bind, checkfirst=True)
