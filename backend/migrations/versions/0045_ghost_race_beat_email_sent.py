"""Phase 4 ghost racing — beat-notification email delivery tracking.

Revision ID: 0045_ghost_race_beat_email_sent
Revises: 0044_ghost_race_beats
Create Date: 2026-08-27 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_ghost_race_beat_email_sent"
down_revision: Union[str, None] = "0044_ghost_race_beats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ghost_race_beats") as batch_op:
        batch_op.add_column(sa.Column("email_sent_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("email_delivered_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ghost_race_beats") as batch_op:
        batch_op.drop_column("email_delivered_at")
        batch_op.drop_column("email_sent_at")
