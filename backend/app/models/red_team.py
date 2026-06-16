import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class RedTeamSession(Base):
    """An attacker-perspective session: the user plays the threat actor."""
    __tablename__ = "red_team_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    # Attack graph state
    current_phase: Mapped[str] = mapped_column(String(100), default="initial_access")
    phases_completed: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    objectives_achieved: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    objectives_failed: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)

    # Blue team AI responses
    blue_team_detections: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    noise_generated: Mapped[int] = mapped_column(Integer, default=0)  # false positives created
    dwell_time_minutes: Mapped[int] = mapped_column(Integer, default=0)

    # Scoring
    stealth_score: Mapped[int] = mapped_column(Integer, default=100)  # starts at 100, drops when detected
    impact_score: Mapped[int] = mapped_column(Integer, default=0)     # rises with objectives achieved
    final_score: Mapped[int] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="active")  # active | success | caught | abandoned
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    scenario: Mapped["Scenario"] = relationship("Scenario")
    user: Mapped["User"] = relationship("User")
    moves: Mapped[list["RedTeamMove"]] = relationship("RedTeamMove", back_populates="session", cascade="all, delete-orphan")


class RedTeamMove(Base):
    """Each attacker action taken during a red team session."""
    __tablename__ = "red_team_moves"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String, ForeignKey("red_team_sessions.id"), nullable=False)
    move_number: Mapped[int] = mapped_column(Integer, nullable=False)

    phase: Mapped[str] = mapped_column(String(100), nullable=False)
    tactic: Mapped[str] = mapped_column(String(200), nullable=False)   # e.g. "Spearphishing Link"
    technique_id: Mapped[str] = mapped_column(String(20), nullable=True)  # MITRE T-code
    tool_used: Mapped[str] = mapped_column(String(200), nullable=True)  # e.g. "Mimikatz", "Cobalt Strike"
    target: Mapped[str] = mapped_column(String(200), nullable=True)    # target asset/user/system

    # Outcome
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detected: Mapped[bool] = mapped_column(Boolean, default=False)
    blue_team_response: Mapped[str] = mapped_column(Text, nullable=True)  # AI-generated defender reaction
    consequence: Mapped[str] = mapped_column(Text, nullable=True)
    stealth_delta: Mapped[int] = mapped_column(Integer, default=0)   # negative = detected
    impact_delta: Mapped[int] = mapped_column(Integer, default=0)    # positive = progress

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["RedTeamSession"] = relationship("RedTeamSession", back_populates="moves")
