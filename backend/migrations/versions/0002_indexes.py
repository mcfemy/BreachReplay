"""add performance indexes

Revision ID: 0002_indexes
Revises: 0001_baseline
Create Date: 2026-05-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0002_indexes"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_simulation_sessions_host_user_id", "simulation_sessions", ["host_user_id"])
    op.create_index("ix_simulation_sessions_organization_id", "simulation_sessions", ["organization_id"])
    op.create_index("ix_simulation_sessions_status", "simulation_sessions", ["status"])
    op.create_index("ix_session_decisions_session_id", "session_decisions", ["session_id"])
    op.create_index("ix_session_decisions_user_id", "session_decisions", ["user_id"])
    op.create_index("ix_scenarios_status", "scenarios", ["status"])
    op.create_index("ix_scenarios_industry_vertical", "scenarios", ["industry_vertical"])
    op.create_index("ix_scenarios_difficulty", "scenarios", ["difficulty"])


def downgrade() -> None:
    op.drop_index("ix_scenarios_difficulty", table_name="scenarios")
    op.drop_index("ix_scenarios_industry_vertical", table_name="scenarios")
    op.drop_index("ix_scenarios_status", table_name="scenarios")
    op.drop_index("ix_session_decisions_user_id", table_name="session_decisions")
    op.drop_index("ix_session_decisions_session_id", table_name="session_decisions")
    op.drop_index("ix_simulation_sessions_status", table_name="simulation_sessions")
    op.drop_index("ix_simulation_sessions_organization_id", table_name="simulation_sessions")
    op.drop_index("ix_simulation_sessions_host_user_id", table_name="simulation_sessions")
