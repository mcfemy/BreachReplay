"""Add environment_state to red_team_sessions

Revision ID: 0020_redteam_environment
Revises: 0019_content_assignments
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_redteam_environment"
down_revision = "0019_content_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "red_team_sessions",
        sa.Column("environment_state", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("red_team_sessions", "environment_state")
