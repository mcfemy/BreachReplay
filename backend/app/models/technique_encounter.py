import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class TechniqueEncounter(Base):
    """ORM mirror of the `technique_encounters` table (migration 0039) — the
    Technique Dossier's per-user rollup: one row per (user_id, technique_id)
    tracking how many times an authenticated player's Action Console run has
    crossed a stage tagged with that MITRE technique (see
    `verb_engine.RunState.encountered_technique_ids` /
    `verb_engine._advance_stages`), regardless of whether they contained it
    correctly.

    Same "user_id + technique_id rollup" shape as `SessionDecision` uses for
    Org Tabletop's mastery data (see `mastery_service.py`), but deliberately
    a SEPARATE table — the Technique Dossier isn't per-decision (attempts/
    correct/accuracy_pct), it's per-encounter (has this player ever seen
    this technique in a run, and how many times), and its source is
    Action Console runs, not `SessionDecision`. Reusing `SessionDecision`
    itself would blur two independent systems together.

    `user_id` has no `nullable=True` unlike `ActionRun.user_id` — rows here
    are only ever written for authenticated runs (see
    `action_run_store.finalize`'s persistence gate); an unauthenticated
    teaser run never reaches this table at all."""

    __tablename__ = "technique_encounters"
    __table_args__ = (
        UniqueConstraint("user_id", "technique_id", name="uq_technique_encounter_user_technique"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    technique_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    encounter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_encountered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_encountered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
