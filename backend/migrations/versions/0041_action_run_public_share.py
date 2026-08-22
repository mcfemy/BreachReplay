"""Add public share-link support for completed Action Console runs.

Mirrors 0025_arena_public_share: an opaque share_token is lazily minted at
POST /action-runs/{id}/share (never backfilled, never a raw run_id in the
URL) and resolved by the unauthenticated GET /action-runs/public/replay/{token}.

public_snapshot is the freeze-at-finalize cache (same reason Arena writes
final_org_state_cache at match complete): the public GET must never call
compile_scenario / apply_verb / replay against a seed on a crawled
endpoint. Contents are already redacted (fog-gated hosts, verb timeline
without targets, technique name/description only) — the GET builder
re-locks the same key sets as defense in depth.

Revision ID: 0041_action_run_public_share
Revises: 0040_user_verb_coachmarks
Create Date: 2026-08-22 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0041_action_run_public_share"
down_revision: Union[str, None] = "0040_user_verb_coachmarks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lazily generated at share-mint time, same as arena_matches.share_token
    # — intentionally NOT backfilled, so nullable with no default.
    op.add_column(
        "action_runs",
        sa.Column("share_token", sa.String(32), nullable=True, unique=True),
    )
    op.create_index("ix_action_runs_share_token", "action_runs", ["share_token"])

    op.add_column(
        "action_runs",
        sa.Column(
            "public_snapshot",
            JSONB().with_variant(sa.JSON, "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("action_runs", "public_snapshot")
    op.drop_index("ix_action_runs_share_token", table_name="action_runs")
    op.drop_column("action_runs", "share_token")
