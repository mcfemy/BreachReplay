"""Add investigation_log to simulation_sessions and hidden_iocs to scenarios

Revision ID: 0017_investigation_surface
Revises: 0016_mfa_saml
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017_investigation_surface"
down_revision = "0016_mfa_saml"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column("investigation_log", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "scenarios",
        sa.Column("hidden_iocs", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scenarios", "hidden_iocs")
    op.drop_column("simulation_sessions", "investigation_log")
