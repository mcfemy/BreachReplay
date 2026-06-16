import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class SimulationSession(Base):
    __tablename__ = "simulation_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id"), nullable=False)
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=True)
    host_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    status: Mapped[str] = mapped_column(SAEnum("waiting", "active", "paused", "completed", "abandoned", name="session_status"), default="waiting")
    mode: Mapped[str] = mapped_column(SAEnum("solo", "multiplayer", name="session_mode"), default="solo")

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    current_alert_index: Mapped[int] = mapped_column(Integer, default=0)
    speed_multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    team_score: Mapped[float] = mapped_column(Float, nullable=True)
    decisions_made: Mapped[int] = mapped_column(Integer, default=0)
    decisions_correct: Mapped[int] = mapped_column(Integer, default=0)

    debrief_report: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    debrief_pdf_key: Mapped[str] = mapped_column(String(500), nullable=True)
    debrief_generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="sessions")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="sessions")
    participants: Mapped[list["SessionParticipant"]] = relationship("SessionParticipant", back_populates="session", cascade="all, delete-orphan")
    decisions: Mapped[list["SessionDecision"]] = relationship("SessionDecision", back_populates="session", cascade="all, delete-orphan")


class SessionParticipant(Base):
    __tablename__ = "session_participants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String, ForeignKey("simulation_sessions.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(SAEnum("incident_commander", "forensic_analyst", "communications_lead", "soc_analyst", "observer", "threat_intel_analyst", "legal_compliance", "network_engineer", name="participant_role"), default="soc_analyst")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=True)

    session: Mapped["SimulationSession"] = relationship("SimulationSession", back_populates="participants")
    user: Mapped["User"] = relationship("User", back_populates="session_participants")


class SessionDecision(Base):
    __tablename__ = "session_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String, ForeignKey("simulation_sessions.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    decision_gate_id: Mapped[str] = mapped_column(String, nullable=False)
    chosen_option_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_time_seconds: Mapped[float] = mapped_column(Float, nullable=True)
    consequence_applied: Mapped[str] = mapped_column(Text, nullable=True)
    nist_control_ref: Mapped[str] = mapped_column(String(100), nullable=True)
    mitre_technique: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["SimulationSession"] = relationship("SimulationSession", back_populates="decisions")
