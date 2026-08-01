import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ConsultingOrg(Base):
    """Phase 2.5 — CMMC Evidence Layer (PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md).
    The RPO/CMMC consultant running exercises on behalf of its clients.
    Deliberately a separate model from `Organization` — that model serves
    the existing enterprise self-serve product line; this one is a
    distinct buyer/product line ("consultant-first, contractor second")
    where cross-tenant isolation is the single highest-severity failure
    mode (spec section 4), so it gets its own tables rather than being
    entangled with Organization's existing SAML/Stripe/audit wiring."""

    __tablename__ = "consulting_orgs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    branding: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    client_orgs: Mapped[list["ClientOrg"]] = relationship("ClientOrg", back_populates="consulting_org", cascade="all, delete-orphan")
    memberships: Mapped[list["Membership"]] = relationship("Membership", back_populates="consulting_org", cascade="all, delete-orphan")


class ClientOrg(Base):
    """The contractor being assessed — belongs to exactly one ConsultingOrg.
    `notification_matrix` is org-declared, not computed (spec section 5):
    who the org must notify, on what basis/channel/window. A JSONB list
    for now, not a separate table — these rows are small and never
    independently filtered/joined against in this build item; splitting
    them out later (once CRUD needs per-row IDs) is a cheap follow-up
    migration, not a redesign."""

    __tablename__ = "client_orgs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # RESTRICT, not CASCADE: deleting a ConsultingOrg must never silently
    # take a client's signed/attested evidence data down with it. A
    # consulting org with live client orgs must fail to delete, loudly.
    consulting_org_id: Mapped[str] = mapped_column(String, ForeignKey("consulting_orgs.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    poc_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    poc_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Flat name/version/date string for now (open decision, resolved for
    # this item) — build-order item 5's after-action IRP linkage work may
    # want this structured; deciding now avoids a second migration but is
    # deliberately not over-built ahead of that item's actual requirements.
    irp_reference: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notification_matrix: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    consulting_org: Mapped["ConsultingOrg"] = relationship("ConsultingOrg", back_populates="client_orgs")
    memberships: Mapped[list["Membership"]] = relationship("Membership", back_populates="client_org", cascade="all, delete-orphan")
    evidence_sessions: Mapped[list["EvidenceSession"]] = relationship("EvidenceSession", back_populates="client_org", cascade="all, delete-orphan")
