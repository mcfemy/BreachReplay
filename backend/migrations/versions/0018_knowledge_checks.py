"""Add knowledge_checks and user_knowledge_check_attempts tables

Revision ID: 0018_knowledge_checks
Revises: 0017_investigation_surface
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018_knowledge_checks"
down_revision = "0017_investigation_surface"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_checks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=True),
        sa.Column("technique_id", sa.String(50), nullable=True),
        sa.Column("nist_control_ref", sa.String(50), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", JSONB(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
    )
    op.create_index("ix_knowledge_checks_scenario", "knowledge_checks", ["scenario_id"])
    op.create_index("ix_knowledge_checks_technique", "knowledge_checks", ["technique_id"])
    op.create_index("ix_knowledge_checks_nist", "knowledge_checks", ["nist_control_ref"])

    op.create_table(
        "user_knowledge_check_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_check_id", sa.String(), sa.ForeignKey("knowledge_checks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chosen_index", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_uk_check_attempts_user", "user_knowledge_check_attempts", ["user_id"])
    op.create_index("ix_uk_check_attempts_check", "user_knowledge_check_attempts", ["knowledge_check_id"])


def downgrade():
    op.drop_index("ix_uk_check_attempts_check", "user_knowledge_check_attempts")
    op.drop_index("ix_uk_check_attempts_user", "user_knowledge_check_attempts")
    op.drop_table("user_knowledge_check_attempts")

    op.drop_index("ix_knowledge_checks_nist", "knowledge_checks")
    op.drop_index("ix_knowledge_checks_technique", "knowledge_checks")
    op.drop_index("ix_knowledge_checks_scenario", "knowledge_checks")
    op.drop_table("knowledge_checks")
