"""Phase 2.5 CMMC Evidence Layer — multi-tenancy models (build-order item 1)

Revision ID: 0035_cmmc_evidence_layer_tenancy
Revises: 0034_proportionate_response
Create Date: 2026-07-31 00:00:00.000000

New tables: consulting_orgs, client_orgs, memberships, evidence_sessions.
Plus one new nullable column on the existing action_runs table
(evidence_session_id). See PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md (repo
root) for full feature context — this migration is build-order item 1
only: the multi-tenancy skeleton, no routes/schemas/PDF generation yet.

Deliberately separate from the existing `organizations`/`teams`/
`team_members` tables — this is a distinct product line (RPO/CMMC
consultants and their contractor clients) where cross-tenant isolation is
the single highest-severity failure mode (spec section 4), so it gets its
own tables rather than being entangled with Organization's existing
SAML/Stripe/audit wiring.

`memberships.role` and `action_runs.outcome` (migration 0034) both use
`native_enum=False` (VARCHAR + CHECK) rather than a native Postgres enum —
0034's own docstring explains why: ADD VALUE can't be used in the same
transaction it's added in, and native enums can never cleanly drop old
values. Consistent choice here even though this enum only has 2 values.

`memberships` also carries a CHECK constraint tying `role` to the specific
org FK it implies (not just "exactly one FK is set") plus two PARTIAL
unique indexes (not one 3-column UniqueConstraint, which would silently
permit duplicates — SQL treats every NULL as distinct from every other
NULL for uniqueness purposes, and one of the two org FK columns is always
NULL by the CHECK).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0035_cmmc_evidence_layer_tenancy"
down_revision: Union[str, None] = "0034_proportionate_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = JSONB if bind.dialect.name == "postgresql" else sa.JSON

    op.create_table(
        "consulting_orgs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("branding", json_type, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "client_orgs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("consulting_org_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("poc_name", sa.String(255), nullable=True),
        sa.Column("poc_email", sa.String(255), nullable=True),
        sa.Column("irp_reference", sa.String(500), nullable=True),
        sa.Column("notification_matrix", json_type, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        # RESTRICT: deleting a ConsultingOrg must never silently take a
        # client's signed/attested evidence data down with it.
        sa.ForeignKeyConstraint(["consulting_org_id"], ["consulting_orgs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_client_orgs_consulting_org_id", "client_orgs", ["consulting_org_id"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("consulting_org_id", sa.String(), nullable=True),
        sa.Column("client_org_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["consulting_org_id"], ["consulting_orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_org_id"], ["client_orgs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(role = 'consultant_admin' AND consulting_org_id IS NOT NULL AND client_org_id IS NULL) "
            "OR (role = 'client_participant' AND client_org_id IS NOT NULL AND consulting_org_id IS NULL)",
            name="ck_membership_role_matches_org",
        ),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_consulting_org_id", "memberships", ["consulting_org_id"])
    op.create_index("ix_memberships_client_org_id", "memberships", ["client_org_id"])
    op.create_index(
        "uq_membership_user_consulting_org", "memberships", ["user_id", "consulting_org_id"],
        unique=True,
        postgresql_where=sa.text("consulting_org_id IS NOT NULL"),
        sqlite_where=sa.text("consulting_org_id IS NOT NULL"),
    )
    op.create_index(
        "uq_membership_user_client_org", "memberships", ["user_id", "client_org_id"],
        unique=True,
        postgresql_where=sa.text("client_org_id IS NOT NULL"),
        sqlite_where=sa.text("client_org_id IS NOT NULL"),
    )

    op.create_table(
        "evidence_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_org_id", sa.String(), nullable=False),
        sa.Column("scenario_id", sa.String(), nullable=False),
        sa.Column("exercise_date", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        # After-action stub columns (build-order item 5 populates these).
        sa.Column("lessons_learned", json_type, nullable=False, server_default="[]"),
        sa.Column("remediation_items", json_type, nullable=False, server_default="[]"),
        sa.Column("client_signoff", json_type, nullable=True),
        sa.Column("consultant_signoff", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # RESTRICT — same reasoning as client_orgs -> consulting_orgs above.
        sa.ForeignKeyConstraint(["client_org_id"], ["client_orgs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_evidence_sessions_client_org_id", "evidence_sessions", ["client_org_id"])
    op.create_index("ix_evidence_sessions_scenario_id", "evidence_sessions", ["scenario_id"])

    # Batch mode with recreate="always", confirmed by testing (not
    # assumed) — three real, separate SQLite/Alembic issues chained into
    # this one line:
    #   1. Alembic's SQLite dialect flatly refuses to ALTER-add a
    #      constraint outside batch mode ("No support for ALTER of
    #      constraints in SQLite dialect"), which a FK column triggers
    #      even with an inline REFERENCES — Alembic models the FK as a
    #      separate constraint-add step regardless. Batch mode is required.
    #   2. Batch mode's default recreate="auto" heuristic doesn't detect
    #      that this particular add needs a full recreate, picks
    #      lightweight ALTER instead, and only then discovers ALTER can't
    #      express the FK — recreate="always" forces the correct strategy
    #      up front instead of Alembic guessing wrong.
    #   3. Once genuinely recreating, batch mode's automatic column-
    #      reordering pass throws a spurious CircularDependencyError
    #      against action_runs' existing column set unless given an
    #      explicit placement hint — insert_after="created_at" (the last
    #      existing column) resolves it deterministically.
    with op.batch_alter_table("action_runs", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "evidence_session_id", sa.String(),
                sa.ForeignKey("evidence_sessions.id", ondelete="SET NULL", name="fk_action_runs_evidence_session_id"),
                nullable=True,
            ),
            insert_after="created_at",
        )
    op.create_index("ix_action_runs_evidence_session_id", "action_runs", ["evidence_session_id"])


def downgrade() -> None:
    op.drop_index("ix_action_runs_evidence_session_id", table_name="action_runs")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("fk_action_runs_evidence_session_id", "action_runs", type_="foreignkey")
        op.drop_column("action_runs", "evidence_session_id")
    else:
        # SQLite refuses a plain ALTER TABLE DROP COLUMN when the column
        # carries a foreign key ("column cannot be dropped ... if it is
        # used in a foreign key constraint") — confirmed by testing, not
        # assumed. Batch mode (full table recreate) is the only way to
        # drop it on SQLite. Upgrade's plain add_column doesn't hit this:
        # only DROP triggers SQLite's FK-column restriction, and only
        # batch mode's ADD-COLUMN reordering pass (not its drop path) hits
        # the earlier circular-dependency bug — so upgrade stays non-batch,
        # downgrade needs batch, and neither reintroduces the other's issue.
        with op.batch_alter_table("action_runs") as batch_op:
            batch_op.drop_column("evidence_session_id")

    op.drop_index("ix_evidence_sessions_scenario_id", table_name="evidence_sessions")
    op.drop_index("ix_evidence_sessions_client_org_id", table_name="evidence_sessions")
    op.drop_table("evidence_sessions")

    op.drop_index("uq_membership_user_client_org", table_name="memberships")
    op.drop_index("uq_membership_user_consulting_org", table_name="memberships")
    op.drop_index("ix_memberships_client_org_id", table_name="memberships")
    op.drop_index("ix_memberships_consulting_org_id", table_name="memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")

    op.drop_index("ix_client_orgs_consulting_org_id", table_name="client_orgs")
    op.drop_table("client_orgs")

    op.drop_table("consulting_orgs")
