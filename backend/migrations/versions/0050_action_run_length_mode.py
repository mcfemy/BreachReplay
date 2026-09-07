"""Action Console length mode (compressed vs full) on action_runs.

Revision ID: 0050_action_run_length_mode
Revises: 0049_colonial_notification_matrix
Create Date: 2026-09-07 00:00:00.000000

Persists the solo Action Console length choice and the cap/ratio actually
used for the run, so ghost races, shares, and CMMC evidence packs can
honestly reconstruct what was played. Daily/teaser and pre-existing rows
default to length_mode='compressed'. Org Tabletop (SimulationSession) is
untouched.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050_action_run_length_mode"
down_revision: Union[str, None] = "0049_colonial_notification_matrix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("action_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "length_mode",
                sa.String(length=20),
                nullable=False,
                server_default="compressed",
            )
        )
        batch_op.add_column(sa.Column("cap_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("compression_ratio", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("action_runs") as batch_op:
        batch_op.drop_column("compression_ratio")
        batch_op.drop_column("cap_seconds")
        batch_op.drop_column("length_mode")
