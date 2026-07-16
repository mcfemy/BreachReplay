import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class ActionRun(Base):
    """ORM mirror of the `action_runs` table (migration 0029) — Phase 2's
    action console core loop (BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4).

    One row per completed run, written once at `run.end` (see the Phase 2
    WebSocket wiring item) — never created at run start and updated later,
    since duration/outcome/score are only known once the run is over.
    `action_log` is the single source of truth for replay: the exact
    timestamped verb log `verb_engine.RunState.action_log` produces. This
    is the Phase 4 ghost-racing replay format and what
    `SessionReplayScrubber` reads.

    `user_id` is nullable — a teaser-mode run has no authenticated user yet
    (same pattern as TeaserEvent.user_id, migration 0028).

    `daily_challenge_id` (migration 0030) is set only for mode="daily" runs
    — one per (daily_challenge, user), enforced by
    uq_action_run_daily_challenge_user, mirroring DailyAttempt's existing
    uq_daily_attempt_user constraint on the decision-gate path exactly."""

    __tablename__ = "action_runs"
    __table_args__ = (
        UniqueConstraint("daily_challenge_id", "user_id", name="uq_action_run_daily_challenge_user"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id"), nullable=False, index=True)
    daily_challenge_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("daily_challenges.id"), nullable=True, index=True,
    )
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(
        SAEnum("daily", "scenario", "teaser", name="action_run_mode"),
        nullable=False,
        index=True,
    )
    action_log: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list, server_default="[]")
    score_breakdown: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default="{}")
    # Plain sortable column, deliberately separate from score_breakdown
    # (JSONB) — leaderboard queries (Daily Breach) need ORDER BY a real
    # indexed integer, not a JSONB path.
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(
        SAEnum("win", "loss", "partial", name="action_run_outcome"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
