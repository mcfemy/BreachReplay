"""Add XP, career tier, achievements and xp_transactions

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    # Add XP columns to users
    op.add_column("users", sa.Column("xp_total", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("career_tier", sa.String(50), server_default="recruit", nullable=False))
    op.add_column("users", sa.Column("achievements", JSONB(), server_default="[]", nullable=False))

    # XP transaction log — every XP award is recorded here
    op.create_table(
        "xp_transactions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),   # scenario|daily|redteam|bonus
        sa.Column("source_id", sa.String(), nullable=True),         # session/challenge/redteam id
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_xp_transactions_user", "xp_transactions", ["user_id"])
    op.create_index("ix_xp_transactions_created", "xp_transactions", ["created_at"])


def downgrade():
    op.drop_index("ix_xp_transactions_created")
    op.drop_index("ix_xp_transactions_user")
    op.drop_table("xp_transactions")
    op.drop_column("users", "achievements")
    op.drop_column("users", "career_tier")
    op.drop_column("users", "xp_total")
