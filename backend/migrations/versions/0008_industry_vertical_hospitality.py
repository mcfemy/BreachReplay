"""Add hospitality and supply_chain to industry_vertical enum

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE industry_vertical ADD VALUE IF NOT EXISTS 'hospitality'")
    op.execute("ALTER TYPE industry_vertical ADD VALUE IF NOT EXISTS 'supply_chain'")
    op.execute("ALTER TYPE industry_vertical ADD VALUE IF NOT EXISTS 'critical_infrastructure'")


def downgrade():
    # PostgreSQL does not support removing enum values — downgrade is a no-op
    pass
