import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Enum as SAEnum, JSON
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
    achievements: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    microsoft_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    github_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)

    # MFA / TOTP
    totp_secret: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mfa_backup_codes: Mapped[Optional[list]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)

    # Live Arena Mode (Phase I) — ELO-style rating and record, updated by
    # arena_rating_service.py whenever a match reaches a terminal status.
    arena_rating: Mapped[int] = mapped_column(Integer, default=1200, server_default="1200")
    arena_wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    arena_losses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    arena_matches_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Live Breach Events Phase 1 — public share links (opt-in only: full_name
    # may already be a real name pulled in from OAuth, so it must never be
    # shown on a public replay page by default). arena_profile_public defaults
    # False for every existing row via server_default; public_display_handle
    # is nullable/unique and only meaningful once arena_profile_public is True.
    public_display_handle: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    arena_profile_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Guided first-run (Action Console pre-brief + in-run beats) — set True
    # the moment a player dismisses the pre-brief, so it plays at most once
    # per account. Reset to False from Settings to replay it for testing.
    has_seen_console_intro: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")
    session_participants: Mapped[list["SessionParticipant"]] = relationship("SessionParticipant", back_populates="user")
