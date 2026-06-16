"""Add certifications table

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "certifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cert_key", sa.String(100), nullable=False),
        sa.Column("cert_title", sa.String(200), nullable=False),
        sa.Column("cert_tier", sa.String(20), nullable=False),   # bronze|silver|gold|platinum
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("verify_token", sa.String(64), unique=True, nullable=False),
    )
    op.create_index("ix_certifications_user", "certifications", ["user_id"])
    op.create_index("ix_certifications_key", "certifications", ["cert_key"])
    op.create_unique_constraint("uq_cert_user_key", "certifications", ["user_id", "cert_key"])


def downgrade():
    op.drop_constraint("uq_cert_user_key", "certifications")
    op.drop_index("ix_certifications_key")
    op.drop_index("ix_certifications_user")
    op.drop_table("certifications")
