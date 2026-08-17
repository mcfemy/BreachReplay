"""Technique Dossier — per-user technique_encounters rollup table

Revision ID: 0039_technique_encounters
Revises: 0038_scenario_notification_matrix
Create Date: 2026-08-16 00:00:00.000000

One row per (user_id, technique_id): how many Action Console runs have
crossed a stage tagged with that MITRE technique (see
`verb_engine.RunState.encountered_technique_ids`), persisted only for
authenticated runs (`action_run_store.finalize`'s persistence gate) — an
unauthenticated teaser run never writes here. Backs `GET /dossier/me`
(`app/services/dossier_service.py`), which joins this table's rows against
`backend/app/services/technique_dossier.py`'s static TECHNIQUE_DOSSIER
content for display.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0039_technique_encounters"
down_revision: Union[str, None] = "0038_scenario_notification_matrix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "technique_encounters",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("technique_id", sa.String(length=100), nullable=False),
        sa.Column("encounter_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_encountered_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_encountered_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "technique_id", name="uq_technique_encounter_user_technique"),
    )
    op.create_index("ix_technique_encounters_user_id", "technique_encounters", ["user_id"])
    op.create_index("ix_technique_encounters_technique_id", "technique_encounters", ["technique_id"])


def downgrade() -> None:
    op.drop_index("ix_technique_encounters_technique_id", table_name="technique_encounters")
    op.drop_index("ix_technique_encounters_user_id", table_name="technique_encounters")
    op.drop_table("technique_encounters")
