import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(SAEnum("owner", "admin", "analyst", "viewer", name="user_role"), default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=True)
    xp_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    career_tier: Mapped[str] = mapped_column(String(50), default="recruit", server_default="recruit")
    achievements: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    microsoft_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    github_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")
    session_participants: Mapped[list["SessionParticipant"]] = relationship("SessionParticipant", back_populates="user")
