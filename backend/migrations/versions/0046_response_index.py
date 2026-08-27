"""Phase 4 — per-user Incident Response Index (ghost-race beats).

Separate from arena_rating / Arena ELO. Bumped when a racer beats a ghost;
not tied to the public cohort Global Index page.

Revision ID: 0046_response_index
Revises: 0045_ghost_race_beat_email_sent
Create Date: 2026-08-28 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_response_index"
down_revision: Union[str, None] = "0045_ghost_race_beat_email_sent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "response_index",
                sa.Integer(),
                nullable=False,
                server_default="1200",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("response_index")
