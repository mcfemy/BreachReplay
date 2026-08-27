import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GhostRaceBeat(Base):
    """Recorded when a ghost-race finisher beats the opponent's containment time.

    Written at action_run_store.finalize() — no email is sent here; a later
    slice reads these rows (filtered by ghost_owner_beat_notifications_enabled
    at send time) to notify ghost owners.
    """

    __tablename__ = "ghost_race_beats"
    __table_args__ = (
        UniqueConstraint("racer_action_run_id", name="uq_ghost_race_beats_racer_action_run"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    racer_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    racer_action_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("action_runs.id"), nullable=False,
    )
    ghost_action_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("action_runs.id"), nullable=False, index=True,
    )
    ghost_owner_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True,
    )
    ghost_owner_beat_notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    racer_containment_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    ghost_containment_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    beat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    # Set once email processing completes (sent or intentionally skipped).
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Set only when SendGrid actually delivers — used for per-owner daily cap.
    email_delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
