"""Add action_runs.daily_challenge_id (Phase 2 Item 4 — Daily Breach action mode)

Revision ID: 0030_action_runs_daily_challenge
Revises: 0029_action_runs
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0030_action_runs_daily_challenge"
down_revision: Union[str, None] = "0029_action_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table: SQLite has no native ALTER TABLE ADD CONSTRAINT
    # (raises NotImplementedError outside of Alembic's copy-and-move batch
    # mode) — needed so this migration's round-trip test
    # (tests/test_action_runs_daily_challenge_migration.py) can run against
    # SQLite. On Postgres, batch mode transparently emits the same plain
    # ALTER TABLE statements op.add_column/create_foreign_key/etc. would.
    with op.batch_alter_table("action_runs") as batch_op:
        # Nullable — only "daily" mode runs are tied to a DailyChallenge;
        # "scenario"/"teaser" runs leave this NULL.
        batch_op.add_column(sa.Column("daily_challenge_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_action_runs_daily_challenge_id",
            "daily_challenges",
            ["daily_challenge_id"],
            ["id"],
        )
        batch_op.create_index("ix_action_runs_daily_challenge_id", ["daily_challenge_id"])
        # One action-mode run per user per daily challenge — mirrors
        # DailyAttempt's existing uq_daily_attempt_user constraint on the
        # decision-gate path exactly. NULL daily_challenge_id values (every
        # scenario/teaser-mode row) are exempt from uniqueness under both
        # Postgres and SQLite — a UNIQUE constraint never considers two
        # NULLs a duplicate — so this only ever constrains real daily rows.
        batch_op.create_unique_constraint(
            "uq_action_run_daily_challenge_user",
            ["daily_challenge_id", "user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("action_runs") as batch_op:
        batch_op.drop_constraint("uq_action_run_daily_challenge_user", type_="unique")
        batch_op.drop_index("ix_action_runs_daily_challenge_id")
        batch_op.drop_constraint("fk_action_runs_daily_challenge_id", type_="foreignkey")
        batch_op.drop_column("daily_challenge_id")
