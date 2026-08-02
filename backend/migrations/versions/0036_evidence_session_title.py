"""Add evidence_sessions.title — build-order item 3 (EvidenceSession
designation from completed runs). Item 1's original stub columns
(exercise_date, scenario_id, lessons_learned, remediation_items,
client_signoff, consultant_signoff) never included a title; item 3's
create/update routes need one to identify a session ("Q3 2026 Tabletop —
Acme Contracting") independent of its scenario/date.

NOT NULL with a server_default: not because any real row should ever get
the default, but because SQLite's ALTER TABLE ADD COLUMN refuses a NOT
NULL column with no default regardless of whether the table currently has
rows (a DDL-level restriction, not a data one) — mirrors migration 0033's
has_seen_console_intro precedent. In practice this default is never
exercised: evidence_sessions has zero rows in any real deployment as of
this migration (items 1-2 only created the table; item 3 is the first
code that ever inserts a row), and the create route's schema requires a
non-empty title at the application layer regardless.

Revision ID: 0036_evidence_session_title
Revises: 0035_cmmc_evidence_layer_tenancy
Create Date: 2026-08-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0036_evidence_session_title"
down_revision: Union[str, None] = "0035_cmmc_evidence_layer_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("evidence_sessions") as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(255), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("evidence_sessions") as batch_op:
        batch_op.drop_column("title")
