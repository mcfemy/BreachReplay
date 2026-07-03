"""Add arena ELO rating/record columns to users (Live Arena Mode Phase I)

Revision ID: 0024_arena_rating
Revises: 0023_arena_difficulty
Create Date: 2026-07-03 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0024_arena_rating"
down_revision: Union[str, None] = "0023_arena_difficulty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("arena_rating", sa.Integer(), nullable=False, server_default="1200"),
    )
    op.add_column(
        "users",
        sa.Column("arena_wins", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("arena_losses", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("arena_matches_played", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "arena_matches_played")
    op.drop_column("users", "arena_losses")
    op.drop_column("users", "arena_wins")
    op.drop_column("users", "arena_rating")
