"""Add MFA fields to users and create organization_saml_configs table

Revision ID: 0016_mfa_saml
Revises: 0015_multi_idp
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016_mfa_saml"
down_revision = "0015_multi_idp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MFA fields on users
    op.add_column("users", sa.Column("totp_secret", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False,
                                     server_default="false"))
    op.add_column("users", sa.Column("mfa_backup_codes", JSONB(), nullable=True))

    # SAML config per organization
    op.create_table(
        "organization_saml_configs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id"),
                  nullable=False, unique=True),
        sa.Column("domain", sa.String(255), nullable=False, unique=True),
        sa.Column("idp_entity_id", sa.String(500), nullable=False),
        sa.Column("idp_sso_url", sa.String(500), nullable=False),
        sa.Column("idp_x509_cert", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_org_saml_configs_domain", "organization_saml_configs", ["domain"])


def downgrade() -> None:
    op.drop_index("ix_org_saml_configs_domain", table_name="organization_saml_configs")
    op.drop_table("organization_saml_configs")

    op.drop_column("users", "mfa_backup_codes")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "totp_secret")
