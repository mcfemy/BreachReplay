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

    industry_vertical: Mapped[str] = mapped_column(SAEnum("healthcare", "energy", "finance", "government", "technology", "retail", "education", "other", name="industry_vertical"), nullable=True)
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
    debrief_skeleton: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)

    status: Mapped[str] = mapped_column(SAEnum("draft", "review", "approved", "rejected", "archived", name="scenario_status"), default="draft")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
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
