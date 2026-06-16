"""baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    org_tier = postgresql.ENUM("starter", "team", "enterprise", "mssp", name="org_tier", create_type=False)
    user_role = postgresql.ENUM("admin", "ciso", "analyst", "observer", name="user_role", create_type=False)
    source_type = postgresql.ENUM("cisa", "sec_8k", "hhs", "verizon_dbir", "private", "manual", name="source_type", create_type=False)
    industry_vertical = postgresql.ENUM("healthcare", "energy", "finance", "government", "technology", "retail", "education", "other", name="industry_vertical", create_type=False)
    difficulty_level = postgresql.ENUM("awareness", "practitioner", "expert", name="difficulty_level", create_type=False)
    scenario_status = postgresql.ENUM("draft", "review", "approved", "rejected", "archived", name="scenario_status", create_type=False)
    session_status = postgresql.ENUM("waiting", "active", "paused", "completed", "abandoned", name="session_status", create_type=False)
    session_mode = postgresql.ENUM("solo", "multiplayer", name="session_mode", create_type=False)
    participant_role = postgresql.ENUM("incident_commander", "forensic_analyst", "communications_lead", "soc_analyst", "observer", name="participant_role", create_type=False)

    bind = op.get_bind()
    for enum in (org_tier, user_role, source_type, industry_vertical, difficulty_level, scenario_status, session_status, session_mode, participant_role):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("tier", org_tier, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_document_key", sa.String(length=500), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("incident_date", sa.DateTime(), nullable=True),
        sa.Column("incident_duration_hours", sa.Float(), nullable=True),
        sa.Column("industry_vertical", industry_vertical, nullable=True),
        sa.Column("initial_access_vector", sa.String(length=255), nullable=True),
        sa.Column("affected_asset_types", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("mitre_techniques", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("nist_controls", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("regulatory_frameworks", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("difficulty", difficulty_level, nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("compression_ratio", sa.Float(), nullable=False),
        sa.Column("alert_sequence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decision_tree", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("debrief_skeleton", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", scenario_status, nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column("owner_org_id", sa.String(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("play_count", sa.Integer(), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "simulation_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scenario_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.Column("host_user_id", sa.String(), nullable=False),
        sa.Column("status", session_status, nullable=False),
        sa.Column("mode", session_mode, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("current_alert_index", sa.Integer(), nullable=False),
        sa.Column("speed_multiplier", sa.Float(), nullable=False),
        sa.Column("team_score", sa.Float(), nullable=True),
        sa.Column("decisions_made", sa.Integer(), nullable=False),
        sa.Column("decisions_correct", sa.Integer(), nullable=False),
        sa.Column("debrief_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("debrief_pdf_key", sa.String(length=500), nullable=True),
        sa.Column("debrief_generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["host_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "session_participants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", participant_role, nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("is_connected", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["simulation_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "session_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("decision_gate_id", sa.String(), nullable=False),
        sa.Column("chosen_option_index", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("response_time_seconds", sa.Float(), nullable=True),
        sa.Column("consequence_applied", sa.Text(), nullable=True),
        sa.Column("nist_control_ref", sa.String(length=100), nullable=True),
        sa.Column("mitre_technique", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["simulation_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("session_decisions")
    op.drop_table("session_participants")
    op.drop_table("simulation_sessions")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("scenarios")
    op.drop_table("organizations")

    bind = op.get_bind()
    for enum_name in ("participant_role", "session_mode", "session_status", "scenario_status", "difficulty_level", "industry_vertical", "source_type", "user_role", "org_tier"):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
