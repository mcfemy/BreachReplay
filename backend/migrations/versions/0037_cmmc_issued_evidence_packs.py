"""Phase 2.5 CMMC Evidence Layer — issued_evidence_packs (build-order
item 7: signing and tamper-evidence)

Revision ID: 0037_cmmc_issued_evidence_packs
Revises: 0036_evidence_session_title
Create Date: 2026-08-06 00:00:00.000000

The permanent record of a signed, issued evidence pack: document ID
(=`id`), the evidence session it evidences, the SHA-256 hash and Ed25519
signature of the exact PDF bytes issued, which key signed it (for
rotation — verification looks up this key_id, never "whichever key is
active now"), who issued it and when, and where the actual bytes are
stored on disk.

`evidence_session_id` is UNIQUE — at most one issued pack per session,
matching the /issue route's idempotent design. RESTRICT, same reasoning
as every other evidence-integrity FK in this layer: deleting an
EvidenceSession must never silently take a signed, issued artifact down
with it.

A plain create_table — no ALTER of a live table, so none of migration
0035's SQLite batch-mode dialect-branching complexity applies here.
Still rehearsed against a real throwaway Postgres before deploy, per
Femi's explicit instruction (same as 0034/0035), even though this one is
simple.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0037_cmmc_issued_evidence_packs"
down_revision: Union[str, None] = "0036_evidence_session_title"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "issued_evidence_packs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("evidence_session_id", sa.String(), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("issued_by_user_id", sa.String(), nullable=True),
        sa.Column("pdf_path", sa.String(500), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["evidence_session_id"], ["evidence_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "uq_issued_evidence_packs_evidence_session_id", "issued_evidence_packs", ["evidence_session_id"], unique=True,
    )
    op.create_index("ix_issued_evidence_packs_sha256_hash", "issued_evidence_packs", ["sha256_hash"])


def downgrade() -> None:
    op.drop_index("ix_issued_evidence_packs_sha256_hash", table_name="issued_evidence_packs")
    op.drop_index("uq_issued_evidence_packs_evidence_session_id", table_name="issued_evidence_packs")
    op.drop_table("issued_evidence_packs")
