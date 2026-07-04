"""Add compound stats index for Arena public aggregate stats (Live Breach Events Phase 3)

Revision ID: 0026_arena_stats_index
Revises: 0025_arena_public_share
Create Date: 2026-07-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0026_arena_stats_index"
down_revision: Union[str, None] = "0025_arena_public_share"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backs GET /arena/public/stats/global-index (no auth) — a public,
    # frequently-hit endpoint against a growing table. That route's single
    # query filters on status IN (...) + completed_at IS NOT NULL (fetching
    # every archetype's rows in one round trip, then grouping by
    # archetype_key in Python) — it never filters ON archetype_key. Column
    # order (status, completed_at) leads with the two columns actually used
    # in the WHERE clause so the query can use an index scan instead of a
    # sequential scan as arena_matches grows; archetype_key is appended so
    # the index can still cover the SELECT (index-only scan) without a
    # separate heap fetch.
    op.create_index(
        "ix_arena_matches_status_completed_archetype",
        "arena_matches",
        ["status", "completed_at", "archetype_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_arena_matches_status_completed_archetype", table_name="arena_matches")
