"""Add daily_challenges and daily_attempts tables

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_challenges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("challenge_date", sa.Date(), nullable=False, unique=True),
        sa.Column("challenge_number", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("total_attempts", sa.Integer(), default=0),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_daily_challenges_date", "daily_challenges", ["challenge_date"])

    op.create_table(
        "daily_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("daily_challenge_id", sa.String(), sa.ForeignKey("daily_challenges.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, default=0),
        sa.Column("decisions_correct", sa.Integer(), default=0),
        sa.Column("decisions_total", sa.Integer(), default=0),
        sa.Column("decision_log", JSONB(), nullable=True),
        sa.Column("time_taken_seconds", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_daily_attempts_challenge_user", "daily_attempts", ["daily_challenge_id", "user_id"], unique=True)
    op.create_index("ix_daily_attempts_score", "daily_attempts", ["daily_challenge_id", "score"])

    # Streak tracking per user
    op.create_table(
        "user_streaks",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("current_streak", sa.Integer(), default=0),
        sa.Column("longest_streak", sa.Integer(), default=0),
        sa.Column("last_played_date", sa.Date(), nullable=True),
        sa.Column("total_dailies_played", sa.Integer(), default=0),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("user_streaks")
    op.drop_index("ix_daily_attempts_score")
    op.drop_index("ix_daily_attempts_challenge_user")
    op.drop_table("daily_attempts")
    op.drop_index("ix_daily_challenges_date")
    op.drop_table("daily_challenges")
