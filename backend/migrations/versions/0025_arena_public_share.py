"""Add public share-link support for Arena matches (Live Breach Events Phase 1)

Revision ID: 0025_arena_public_share
Revises: 0024_arena_rating
Create Date: 2026-07-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0025_arena_public_share"
down_revision: Union[str, None] = "0024_arena_rating"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # share_token is lazily generated at request time (POST /arena/matches/{id}/share)
    # — intentionally NOT backfilled for existing rows, so nullable with no default.
    op.add_column(
        "arena_matches",
        sa.Column("share_token", sa.String(32), nullable=True, unique=True),
    )
    op.create_index("ix_arena_matches_share_token", "arena_matches", ["share_token"])

    op.add_column(
        "users",
        sa.Column("public_display_handle", sa.String(50), nullable=True, unique=True),
    )
    op.create_index("ix_users_public_display_handle", "users", ["public_display_handle"])
    op.add_column(
        "users",
        sa.Column("arena_profile_public", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "arena_profile_public")
    op.drop_index("ix_users_public_display_handle", table_name="users")
    op.drop_column("users", "public_display_handle")

    op.drop_index("ix_arena_matches_share_token", table_name="arena_matches")
    op.drop_column("arena_matches", "share_token")
