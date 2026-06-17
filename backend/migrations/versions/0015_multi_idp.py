"""Add microsoft_id and github_id for multi-IdP OAuth

Revision ID: 0015_multi_idp
Revises: 0014_google_oauth
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_multi_idp"
down_revision = "0014_google_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("microsoft_id", sa.String(255), nullable=True, unique=True))
    op.create_index("ix_users_microsoft_id", "users", ["microsoft_id"])

    op.add_column("users", sa.Column("github_id", sa.String(255), nullable=True, unique=True))
    op.create_index("ix_users_github_id", "users", ["github_id"])


def downgrade() -> None:
    op.drop_index("ix_users_github_id", table_name="users")
    op.drop_column("users", "github_id")

    op.drop_index("ix_users_microsoft_id", table_name="users")
    op.drop_column("users", "microsoft_id")
