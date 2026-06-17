"""Add google_id for OAuth SSO

Revision ID: 0014_google_oauth
Revises: 0013_teams
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_google_oauth"
down_revision = "0013_teams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_id", sa.String(255), nullable=True, unique=True))
    op.create_index("ix_users_google_id", "users", ["google_id"])


def downgrade() -> None:
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "google_id")
