"""Add users.seen_verb_coachmarks — server-side per-user, per-verb tracking
of which Action Console verb coachmarks (the anchored first-use tooltips)
this account has already dismissed, so each of the 8 verbs' tooltip fires
at most once ever. Sibling of 0033_user_console_intro's has_seen_console_intro,
one level more granular (per-verb list instead of a single account-wide flag).

Revision ID: 0040_user_verb_coachmarks
Revises: 0039_technique_encounters
Create Date: 2026-08-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0040_user_verb_coachmarks"
down_revision: Union[str, None] = "0039_technique_encounters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        # server_default "[]" so every existing account backfills to an
        # empty list (i.e. still sees every verb's coachmark once) in the
        # same DDL, matching 0033's has_seen_console_intro backfill.
        batch_op.add_column(
            sa.Column(
                "seen_verb_coachmarks",
                JSONB().with_variant(sa.JSON, "sqlite"),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("seen_verb_coachmarks")
