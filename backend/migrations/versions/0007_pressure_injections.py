"""Add pressure_injections column to scenarios

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scenarios", sa.Column("pressure_injections", JSONB(), nullable=True))


def downgrade():
    op.drop_column("scenarios", "pressure_injections")
