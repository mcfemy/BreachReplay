"""Add users.has_seen_console_intro — server-side per-user tracking of
whether the guided first-run (Action Console pre-brief + in-run beats) has
already played for this account, so it fires at most once ever.

Numbered 0033, not 0032: 0032_outreach_contacts.py already exists chained
off 0031_scenario_is_synthetic on the unmerged phase-boundary-restructure
branch. down_revision stays pinned to 0031 regardless of which of the two
lands first — whoever merges the second one resolves the chain deliberately.

Revision ID: 0033_user_console_intro
Revises: 0031_scenario_is_synthetic
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0033_user_console_intro"
down_revision: Union[str, None] = "0031_scenario_is_synthetic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        # server_default "false" so every existing account backfills to
        # False (i.e. still sees the guided first-run once) in the same DDL.
        batch_op.add_column(
            sa.Column("has_seen_console_intro", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("has_seen_console_intro")
