import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, CheckConstraint, Index, text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class Membership(Base):
    """user <-> (ConsultingOrg | ClientOrg), with a role. Mirrors
    TeamMember's role-junction shape (app/models/team.py), not the table
    itself — this is a distinct tenancy tree (see cmmc_org.py's docstring).

    A row belongs to exactly ONE of consulting_org_id / client_org_id,
    never both, never neither, and the role must match which one —
    `ck_membership_role_matches_org` makes a consultant_admin row with
    client_org_id set (or the reverse) structurally unrepresentable, not
    just discouraged by convention. This is tighter than a plain "exactly
    one FK is set" check specifically because isolation is this layer's
    highest-severity failure mode (spec section 4) — the constraint itself
    should make the wrong shape impossible, not just unlikely.

    Two PARTIAL unique indexes below, not one 3-column UniqueConstraint —
    SQL treats every NULL as distinct from every other NULL for uniqueness
    purposes, and one of these two FK columns is always NULL by the CHECK
    above, so a plain UNIQUE(user_id, consulting_org_id, client_org_id)
    would silently permit duplicate memberships. Partial indexes (WHERE
    the relevant FK IS NOT NULL) are what actually enforces "one
    membership per (user, org)"."""

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(
            "(role = 'consultant_admin' AND consulting_org_id IS NOT NULL AND client_org_id IS NULL) "
            "OR (role = 'client_participant' AND client_org_id IS NOT NULL AND consulting_org_id IS NULL)",
            name="ck_membership_role_matches_org",
        ),
        Index(
            "uq_membership_user_consulting_org", "user_id", "consulting_org_id",
            unique=True,
            sqlite_where=text("consulting_org_id IS NOT NULL"),
            postgresql_where=text("consulting_org_id IS NOT NULL"),
        ),
        Index(
            "uq_membership_user_client_org", "user_id", "client_org_id",
            unique=True,
            sqlite_where=text("client_org_id IS NOT NULL"),
            postgresql_where=text("client_org_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Both nullable — exactly one is required by ck_membership_role_matches_org.
    consulting_org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("consulting_orgs.id", ondelete="CASCADE"), nullable=True, index=True)
    client_org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("client_orgs.id", ondelete="CASCADE"), nullable=True, index=True)
    # native_enum=False from the start — tonight's Proportionate Response
    # work (migration 0034) hit real pain from native Postgres enums
    # (can't ADD VALUE inside the same transaction that needs it, can never
    # cleanly drop old values). No reason to repeat a mistake already paid
    # for once tonight, even though this enum only has 2 values today.
    role: Mapped[str] = mapped_column(
        SAEnum("consultant_admin", "client_participant", name="cmmc_membership_role", native_enum=False),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    consulting_org: Mapped[Optional["ConsultingOrg"]] = relationship("ConsultingOrg", back_populates="memberships")
    client_org: Mapped[Optional["ClientOrg"]] = relationship("ClientOrg", back_populates="memberships")
    user: Mapped["User"] = relationship("User")
