import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class ContentAssignment(Base):
    """Instructor/cohort assignment — assign a scenario (or a target MITRE technique)
    to a team or an individual user, optionally with a due date. Either team_id or
    user_id identifies the target; either scenario_id or target_technique_id
    identifies the payload."""

    __tablename__ = "content_assignments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=True)
    target_technique_id: Mapped[str] = mapped_column(String(50), nullable=True)
    due_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
