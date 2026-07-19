"""Add scenarios.is_synthetic — excludes test/synthetic content from the
daily-challenge picker structurally (a real flag, not a title match)

Revision ID: 0031_scenario_is_synthetic
Revises: 0030_action_runs_daily_challenge
Create Date: 2026-07-18 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0031_scenario_is_synthetic"
down_revision: Union[str, None] = "0030_action_runs_daily_challenge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("scenarios") as batch_op:
        # server_default "false" so every existing row (all real, authored
        # content today) backfills to False in the same DDL statement —
        # nothing downstream has to special-case a NULL.
        batch_op.add_column(
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # Known leaked test fixtures (backend/tests/*.py's AsyncSessionLocal-based
    # helpers, which persist for real against whatever DB the test suite
    # points at — see docs/BACKLOG.md's "Daily-challenge picker can select
    # synthetic/test-titled scenarios" entry). Flipped out of `approved`
    # AND flagged here as a one-time remediation of pre-existing data;
    # going forward the test fixtures themselves set is_synthetic=True at
    # creation time, so this backfill should never need to run again.
    op.execute(
        """
        UPDATE scenarios
        SET is_synthetic = true, status = 'archived'
        WHERE title IN (
            'WS Handler Test Scenario',
            'Daily Action Mode Test Scenario',
            'Org Tabletop Regression Scenario'
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_column("is_synthetic")
