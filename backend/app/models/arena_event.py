import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ArenaEvent(Base):
    """Live Breach Events Phase 4 — a scheduled, synchronized live arena
    event: many players join at a set time, all play the identical
    seed/archetype/difficulty, and watch a shared live leaderboard tick as
    matches resolve.

    `scenario_id` is DESCRIPTIVE / MARKETING METADATA ONLY. It ties an
    event's copy/ticker/share content to a real ingested incident by name
    (e.g. "Live Replay: Colonial Pipeline") — the whole point of this
    initiative per the Phase 4 plan — but the simulation itself is
    unaffected by it: matches created under this event still run purely off
    `archetype_key` + `seed` through `org_simulation.py`'s pure functions,
    exactly like every other ArenaMatch. No code path reads
    `ArenaEvent.scenario_id` to influence simulated org state.

    `seed`/`archetype_key`/`difficulty` are fixed at event-creation time
    (see `POST /admin/arena/events`) so every match paired under this event
    — human-vs-human or human-vs-AI-bot fallback — plays the identical
    scenario, which is the "synchronized" part of "synchronized live
    events."

    `status` is a simple state machine driven by
    `app.services.arena_event_service.transition_arena_events` (a Celery
    Beat task running every 60s): scheduled -> live at `starts_at`, live ->
    completed at `ends_at`. See that module's docstring for why the
    AI-fallback-fill behavior (pairing stragglers against an AI bot once the
    join window closes) is deliberately NOT triggered from that same task.
    """

    __tablename__ = "arena_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("scenarios.id"), nullable=True)
    archetype_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Reuses the exact same Postgres enum type ArenaMatch.difficulty already
    # declares ("arena_match_difficulty") — both columns share the identical
    # domain of values, and an event's difficulty is copied verbatim onto
    # every ArenaMatch paired under it, so a single shared type is more
    # honest than declaring a second, functionally-identical enum type.
    difficulty: Mapped[str] = mapped_column(
        SAEnum("easy", "medium", "hard", name="arena_match_difficulty"),
        nullable=False,
        default="medium",
        server_default="medium",
    )
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum("scheduled", "live", "completed", "cancelled", name="arena_event_status"),
        nullable=False,
        default="scheduled",
        server_default="scheduled",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    scenario: Mapped[Optional["Scenario"]] = relationship("Scenario")
    matches: Mapped[list["ArenaMatch"]] = relationship("ArenaMatch", back_populates="event")
