import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class EvidenceSession(Base):
    """One exercise, belonging to a ClientOrg — MAY span multiple
    ActionRuns (spec section 4: "a real tabletop is a team exercising
    together... one scenario, several people, one artifact"). The
    many-to-one is required from day one: `ActionRun.evidence_session_id`
    (see action_run.py) is a plain nullable FK, not a join table, since a
    run is written once at run.end and can belong to at most one exercise
    — the same shape as ActionRun's existing `daily_challenge_id`.

    `lessons_learned`/`remediation_items`/`*_signoff` are stub columns for
    build-order item 5's after-action workflow — included in this
    migration now (empty defaults) rather than a second migration later,
    per this session's own 0034 precedent of bundling one conceptual
    schema change into one migration rather than splitting it across two."""

    __tablename__ = "evidence_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # RESTRICT — same reasoning as ConsultingOrg -> ClientOrg (cmmc_org.py):
    # signed/attested evidence must never disappear as a side effect of
    # deleting its parent client org.
    client_org_id: Mapped[str] = mapped_column(String, ForeignKey("client_orgs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id"), nullable=False, index=True)
    exercise_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    lessons_learned: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list, server_default="[]")
    remediation_items: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list, server_default="[]")
    client_signoff: Mapped[Optional[dict]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    consultant_signoff: Mapped[Optional[dict]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)

    client_org: Mapped["ClientOrg"] = relationship("ClientOrg", back_populates="evidence_sessions")
    runs: Mapped[list["ActionRun"]] = relationship("ActionRun", back_populates="evidence_session")
