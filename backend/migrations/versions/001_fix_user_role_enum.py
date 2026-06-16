"""Fix user_role enum to match PHASES.md spec

Revision ID: 001_fix_user_role_enum
Revises:
Create Date: 2026-05-24

Changes:
  - Renames user_role enum values:
      ciso     -> admin  (ciso is a title, not a role level)
      observer -> viewer (aligns with PHASES.md spec)
  - Adds: owner role
  - Removes: ciso, observer roles
"""

from alembic import op

revision = "001_fix_user_role_enum"
down_revision = "0002_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE user_role_new AS ENUM ('owner', 'admin', 'analyst', 'viewer')")
    op.execute("""
        ALTER TABLE users
            ALTER COLUMN role TYPE user_role_new
            USING CASE role::text
                WHEN 'admin'    THEN 'admin'::user_role_new
                WHEN 'ciso'     THEN 'admin'::user_role_new
                WHEN 'analyst'  THEN 'analyst'::user_role_new
                WHEN 'observer' THEN 'viewer'::user_role_new
                ELSE                 'analyst'::user_role_new
            END
    """)
    op.execute("DROP TYPE user_role")
    op.execute("ALTER TYPE user_role_new RENAME TO user_role")


def downgrade() -> None:
    op.execute("CREATE TYPE user_role_old AS ENUM ('admin', 'ciso', 'analyst', 'observer')")
    op.execute("""
        ALTER TABLE users
            ALTER COLUMN role TYPE user_role_old
            USING CASE role::text
                WHEN 'owner'    THEN 'admin'::user_role_old
                WHEN 'admin'    THEN 'admin'::user_role_old
                WHEN 'analyst'  THEN 'analyst'::user_role_old
                WHEN 'viewer'   THEN 'observer'::user_role_old
                ELSE                 'analyst'::user_role_old
            END
    """)
    op.execute("DROP TYPE user_role")
    op.execute("ALTER TYPE user_role_old RENAME TO user_role")
