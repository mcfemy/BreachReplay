import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ArenaMatch(Base):
    """A Live Arena Mode match: a deterministic, seeded simulated-org match between
    an attacker and a defender (human or AI on either side). The action log
    (ArenaAction rows) is the source of truth for match state; final_org_state_cache
    is only a cached replay result for fast debrief loading."""

    __tablename__ = "arena_matches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    archetype_key: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(
        SAEnum("pvp", "human_defends_vs_ai", "human_attacks_vs_ai", name="arena_match_mode"),
        nullable=False,
    )
    attacker_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    defender_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum("lobby", "active", "attacker_won", "defender_won", "abandoned", name="arena_match_status"),
        nullable=False,
        default="lobby",
        server_default="lobby",
    )
    # Threaded through to the AI attacker/defender bot policies (Phase D/E) —
    # see app/websocket/handlers.py's _run_arena_attacker_bot /
    # _apply_defender_bot_response_locked, which now read this column instead
    # of always using the hardcoded _DEFAULT_BOT_DIFFICULTY /
    # _DEFAULT_DEFENDER_BOT_DIFFICULTY constants (those constants remain the
    # fallback default — "medium" — for matches created before this column
    # existed or with no difficulty specified).
    difficulty: Mapped[str] = mapped_column(
        SAEnum("easy", "medium", "hard", name="arena_match_difficulty"),
        nullable=False,
        default="medium",
        server_default="medium",
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    final_org_state_cache: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Live Breach Events Phase 1 — lazily generated (not backfilled) public
    # share token. Only ever set via POST /arena/matches/{id}/share, and only
    # once the match has reached a terminal status. Presence of a token does
    # NOT by itself grant public access to non-terminal matches — the public
    # GET /arena/public/replay/{share_token} route re-checks match.status.
    share_token: Mapped[str] = mapped_column(String(32), nullable=True, unique=True, index=True)

    attacker: Mapped["User"] = relationship("User", foreign_keys=[attacker_user_id])
    defender: Mapped["User"] = relationship("User", foreign_keys=[defender_user_id])
    actions: Mapped[list["ArenaAction"]] = relationship(
        "ArenaAction", back_populates="match", cascade="all, delete-orphan"
    )


class ArenaAction(Base):
    """A single event-sourced action (attacker move or defender response) in an
    ArenaMatch's action log. sequence_number enforces strict ordering per match —
    replay(seed, archetype, actions[]) folds these, in order, through the pure
    simulation functions to reconstruct match state."""

    __tablename__ = "arena_actions"
    __table_args__ = (
        UniqueConstraint("match_id", "sequence_number", name="uq_arena_actions_match_sequence"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("arena_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(SAEnum("attacker", "defender", name="arena_action_actor"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # No default: an event-sourced action with no payload is meaningless in this
    # design (replay() folds payload through the simulation functions), so a
    # caller that forgets to supply one should hit a clear NOT NULL error, not
    # silently log an empty action.
    payload: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    match: Mapped["ArenaMatch"] = relationship("ArenaMatch", back_populates="actions")
