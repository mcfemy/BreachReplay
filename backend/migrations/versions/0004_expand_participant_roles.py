"""Expand participant_role enum to 8-seat capacity

Revision ID: 0004_expand_participant_roles
Revises: 0003_admin_tables
Create Date: 2026-05-26

Adds three new roles to the participant_role PostgreSQL ENUM:
  threat_intel_analyst, legal_compliance, network_engineer

PostgreSQL ENUM values can only be added (never removed) without
a full type replacement. We use ALTER TYPE ... ADD VALUE which is
safe to run on a live table.
"""

from alembic import op

revision = "0004_expand_participant_roles"
down_revision = "0003_admin_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE participant_role ADD VALUE IF NOT EXISTS 'threat_intel_analyst'")
    op.execute("ALTER TYPE participant_role ADD VALUE IF NOT EXISTS 'legal_compliance'")
    op.execute("ALTER TYPE participant_role ADD VALUE IF NOT EXISTS 'network_engineer'")


def downgrade() -> None:
    # PostgreSQL does not support removing ENUM values without full type replacement.
    # Downgrade is intentionally a no-op; removing the values would require recreating
    # the type and all dependent columns, which is not safe for a rollback script.
    pass
