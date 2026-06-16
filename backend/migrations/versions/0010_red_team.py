"""Add red_team_sessions and red_team_moves tables

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "red_team_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("current_phase", sa.String(100), default="initial_access"),
        sa.Column("phases_completed", JSONB(), default=list),
        sa.Column("objectives_achieved", JSONB(), default=list),
        sa.Column("objectives_failed", JSONB(), default=list),
        sa.Column("blue_team_detections", JSONB(), default=list),
        sa.Column("noise_generated", sa.Integer(), default=0),
        sa.Column("dwell_time_minutes", sa.Integer(), default=0),
        sa.Column("stealth_score", sa.Integer(), default=100),
        sa.Column("impact_score", sa.Integer(), default=0),
        sa.Column("final_score", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), default="active"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_red_team_sessions_user", "red_team_sessions", ["user_id"])

    op.create_table(
        "red_team_moves",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("red_team_sessions.id"), nullable=False),
        sa.Column("move_number", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(100), nullable=False),
        sa.Column("tactic", sa.String(200), nullable=False),
        sa.Column("technique_id", sa.String(20), nullable=True),
        sa.Column("tool_used", sa.String(200), nullable=True),
        sa.Column("target", sa.String(200), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("detected", sa.Boolean(), default=False),
        sa.Column("blue_team_response", sa.Text(), nullable=True),
        sa.Column("consequence", sa.Text(), nullable=True),
        sa.Column("stealth_delta", sa.Integer(), default=0),
        sa.Column("impact_delta", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_red_team_moves_session", "red_team_moves", ["session_id"])


def downgrade():
    op.drop_index("ix_red_team_moves_session")
    op.drop_table("red_team_moves")
    op.drop_index("ix_red_team_sessions_user")
    op.drop_table("red_team_sessions")
