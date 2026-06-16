import uuid
from datetime import datetime, date
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class DailyChallenge(Base):
    __tablename__ = "daily_challenges"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id"), nullable=False)
    challenge_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    challenge_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    scenario: Mapped["Scenario"] = relationship("Scenario")
    attempts: Mapped[list["DailyAttempt"]] = relationship("DailyAttempt", back_populates="challenge", cascade="all, delete-orphan")


class DailyAttempt(Base):
    __tablename__ = "daily_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    daily_challenge_id: Mapped[str] = mapped_column(String, ForeignKey("daily_challenges.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decisions_correct: Mapped[int] = mapped_column(Integer, default=0)
    decisions_total: Mapped[int] = mapped_column(Integer, default=0)
    decision_log: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    time_taken_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("daily_challenge_id", "user_id", name="uq_daily_attempt_user"),
    )

    challenge: Mapped["DailyChallenge"] = relationship("DailyChallenge", back_populates="attempts")
    user: Mapped["User"] = relationship("User")


class UserStreak(Base):
    __tablename__ = "user_streaks"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_played_date: Mapped[date] = mapped_column(Date, nullable=True)
    total_dailies_played: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User")
