"""create content_assignments table

Revision ID: 0019_content_assignments
Revises: 0018_knowledge_checks
Create Date: 2026-07-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0019_content_assignments"
down_revision: Union[str, None] = "0018_knowledge_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_assignments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("scenario_id", sa.String(), nullable=True),
        sa.Column("target_technique_id", sa.String(length=50), nullable=True),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_assignments_organization_id", "content_assignments", ["organization_id"])
    op.create_index("ix_content_assignments_team_id", "content_assignments", ["team_id"])
    op.create_index("ix_content_assignments_user_id", "content_assignments", ["user_id"])
    op.create_index("ix_content_assignments_scenario_id", "content_assignments", ["scenario_id"])


def downgrade() -> None:
    op.drop_index("ix_content_assignments_scenario_id", table_name="content_assignments")
    op.drop_index("ix_content_assignments_user_id", table_name="content_assignments")
    op.drop_index("ix_content_assignments_team_id", table_name="content_assignments")
    op.drop_index("ix_content_assignments_organization_id", table_name="content_assignments")
    op.drop_table("content_assignments")
