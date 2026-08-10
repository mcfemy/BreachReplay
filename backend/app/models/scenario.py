import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.db.session import Base


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    source_type: Mapped[str] = mapped_column(SAEnum("cisa", "sec_8k", "hhs", "verizon_dbir", "private", "manual", name="source_type"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    source_document_key: Mapped[str] = mapped_column(String(500), nullable=True)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=True)

    incident_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    incident_duration_hours: Mapped[float] = mapped_column(Float, nullable=True)

    industry_vertical: Mapped[str] = mapped_column(SAEnum("healthcare", "energy", "finance", "government", "technology", "retail", "education", "hospitality", "supply_chain", "critical_infrastructure", "other", name="industry_vertical"), nullable=True)
    initial_access_vector: Mapped[str] = mapped_column(String(255), nullable=True)
    affected_asset_types: Mapped[list] = mapped_column(ARRAY(String).with_variant(JSON, "sqlite"), nullable=True)

    mitre_techniques: Mapped[list] = mapped_column(ARRAY(String).with_variant(JSON, "sqlite"), nullable=True)
    nist_controls: Mapped[list] = mapped_column(ARRAY(String).with_variant(JSON, "sqlite"), nullable=True)
    regulatory_frameworks: Mapped[list] = mapped_column(ARRAY(String).with_variant(JSON, "sqlite"), nullable=True)

    difficulty: Mapped[str] = mapped_column(SAEnum("awareness", "practitioner", "expert", name="difficulty_level"), default="practitioner")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=45)
    compression_ratio: Mapped[float] = mapped_column(Float, default=8.0)

    alert_sequence: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    decision_tree: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    pressure_injections: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    hidden_iocs: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    # Proportionate Response (migration 0034): authored per-hostname
    # collateral severity, {hostname: weight 0-100} — same provenance
    # discipline as hidden_iocs (see backend/seed.py's per-scenario dicts
    # for citations). Keyed by hostname, not host_id: scenario-mode seeds
    # are genuinely random per playthrough (secrets.randbelow), and only a
    # scenario's own host_harvest.harvest_hostnames() set is stable across
    # seeds — see docs/BACKLOG.md's "final-stage target is unbound from
    # real content" entry for the bug this sidesteps. Hosts not present in
    # this dict (i.e. every procedurally-generated one) fall back to
    # verb_engine.DEFAULT_COLLATERAL_WEIGHT. `debrief_skeleton` (dead,
    # zero references anywhere) is retired in the same migration rather
    # than left ambiguous a third time — the new debrief narrative is
    # computed dynamically from outcome + collateral, not stored here.
    collateral_weights: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default="{}",
    )
    # Phase 3 — Targeted Escalation & Notification Proportionality. The
    # scenario's own authored ground truth for which parties a warranted
    # notification decision covers: [{id, party_name, warranted, authority,
    # basis, channel, window, rationale, source_reference}, ...]. NOT the
    # same thing as ClientOrg.notification_matrix (Phase 2.5 item 4) — that
    # is the client org's own generically-declared contact policy, no
    # incident-specific judgment. This is BreachReplay's own per-scenario
    # "was notifying this party actually warranted" call, same authored-
    # content precedent as collateral_weights/hidden_iocs above, not a
    # client declaration. See migration 0038 for the SolarWinds reference
    # content and docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md section 10.
    notification_matrix: Mapped[list] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list, server_default="[]",
    )

    status: Mapped[str] = mapped_column(SAEnum("draft", "review", "approved", "rejected", "archived", name="scenario_status"), default="draft")
    # Structural guard against the daily-challenge picker (and anything else
    # that queries "real playable content") ever selecting test/fixture
    # data — a real column, not a title match, so it can't be defeated by a
    # test fixture picking an ordinary-looking title. Test code that must
    # persist a real (non-rolled-back) `status="approved"` Scenario row for
    # its own purposes sets this True explicitly at creation time; every
    # production scenario defaults False.
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_capstone: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    owner_org_id: Mapped[str] = mapped_column(String, nullable=True)

    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    review_notes: Mapped[str] = mapped_column(Text, nullable=True)
    embedding: Mapped[list] = mapped_column(Vector(384), nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    version_history: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)

    play_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sessions: Mapped[list["SimulationSession"]] = relationship("SimulationSession", back_populates="scenario", cascade="all, delete-orphan")
