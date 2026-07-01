"""Add is_capstone to scenarios

Revision ID: 0021_scenario_capstone
Revises: 0020_redteam_environment
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_scenario_capstone"
down_revision = "0020_redteam_environment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenarios", sa.Column("is_capstone", sa.Boolean(), nullable=False,
                                          server_default="false"))


def downgrade() -> None:
    op.drop_column("scenarios", "is_capstone")
