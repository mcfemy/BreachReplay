import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class TeaserEvent(Base):
    """Analytics/funnel log for the no-auth landing teaser (Phase 1). One row
    per funnel step (teaser_started/teaser_decided/teaser_completed/
    signup_from_teaser), correlated by `token_id` (the signed anonymous
    teaser session token's `tid` claim — never a real user id until
    signup_from_teaser, when `user_id` is set). Funnel counts are just
    COUNT(*) GROUP BY event_type; conversion rate is
    COUNT(signup_from_teaser) / COUNT(teaser_started)."""

    __tablename__ = "teaser_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(
        SAEnum(
            "teaser_started", "teaser_decided", "teaser_completed", "signup_from_teaser",
            name="teaser_event_type",
        ),
        nullable=False,
        index=True,
    )
    token_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
