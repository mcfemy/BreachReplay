"""Add difficulty to arena_matches (Live Arena Mode Phase F)

Revision ID: 0023_arena_difficulty
Revises: 0022_arena_mode
Create Date: 2026-07-02 06:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0023_arena_difficulty"
down_revision: Union[str, None] = "0022_arena_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    arena_match_difficulty = postgresql.ENUM(
        "easy", "medium", "hard", name="arena_match_difficulty", create_type=False
    )
    arena_match_difficulty.create(bind, checkfirst=True)

    op.add_column(
        "arena_matches",
        sa.Column("difficulty", arena_match_difficulty, nullable=False, server_default="medium"),
    )


def downgrade() -> None:
    op.drop_column("arena_matches", "difficulty")

    bind = op.get_bind()
    postgresql.ENUM(name="arena_match_difficulty").drop(bind, checkfirst=True)
