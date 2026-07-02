"""create arena_matches and arena_actions tables (Live Arena Mode Phase A)

Revision ID: 0022_arena_mode
Revises: 0021_scenario_capstone
Create Date: 2026-07-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022_arena_mode"
down_revision: Union[str, None] = "0021_scenario_capstone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    arena_match_mode = postgresql.ENUM(
        "pvp", "human_defends_vs_ai", "human_attacks_vs_ai", name="arena_match_mode", create_type=False
    )
    arena_match_mode.create(bind, checkfirst=True)

    arena_match_status = postgresql.ENUM(
        "lobby", "active", "attacker_won", "defender_won", "abandoned", name="arena_match_status", create_type=False
    )
    arena_match_status.create(bind, checkfirst=True)

    arena_action_actor = postgresql.ENUM(
        "attacker", "defender", name="arena_action_actor", create_type=False
    )
    arena_action_actor.create(bind, checkfirst=True)

    op.create_table(
        "arena_matches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("archetype_key", sa.String(length=100), nullable=False),
        sa.Column("mode", arena_match_mode, nullable=False),
        sa.Column("attacker_user_id", sa.String(), nullable=True),
        sa.Column("defender_user_id", sa.String(), nullable=True),
        sa.Column("status", arena_match_status, nullable=False, server_default="lobby"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("final_org_state_cache", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["attacker_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["defender_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_arena_matches_attacker_user_id", "arena_matches", ["attacker_user_id"])
    op.create_index("ix_arena_matches_defender_user_id", "arena_matches", ["defender_user_id"])

    op.create_table(
        "arena_actions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("match_id", sa.String(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("actor", arena_action_actor, nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["match_id"], ["arena_matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_arena_actions_match_id", "arena_actions", ["match_id"])
    op.create_unique_constraint(
        "uq_arena_actions_match_sequence", "arena_actions", ["match_id", "sequence_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_arena_actions_match_sequence", "arena_actions", type_="unique")
    op.drop_index("ix_arena_actions_match_id", table_name="arena_actions")
    op.drop_table("arena_actions")

    op.drop_index("ix_arena_matches_defender_user_id", table_name="arena_matches")
    op.drop_index("ix_arena_matches_attacker_user_id", table_name="arena_matches")
    op.drop_table("arena_matches")

    bind = op.get_bind()
    postgresql.ENUM(name="arena_action_actor").drop(bind, checkfirst=True)
    postgresql.ENUM(name="arena_match_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="arena_match_mode").drop(bind, checkfirst=True)
