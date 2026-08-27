"""Ghost race beat detection — record when a racer beats a ghost's time.

Ghost containment is looked up fresh from the opponent ActionRun row at
finalize time (via action_run_ghost._containment_seconds) rather than
cached on LiveRun at race start: the ghost row is immutable after finalize,
so duration_seconds remains the single source of truth and we avoid stale
duplicates if the schema ever gains a distinct containment field.

Beat events are always recorded when criteria match, regardless of
ghost_owner_beat_notifications_enabled — that flag is snapshotted for the
future email slice so analytics/history survive opt-out and send-time logic
can still respect current prefs without losing audit data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.ghost_race_beat import GhostRaceBeat
from app.models.user import User
from app.services.action_run_ghost import _containment_seconds

# Beat eligibility is stricter than ghost DTO containment display: overreacted
# ghosts still expose a containment_seconds for comparison, but a racer must
# finish contained or contained_at_cost to count as beating the ghost.
BEAT_RACER_OUTCOMES = frozenset({"contained", "contained_at_cost"})


def is_ghost_race_beat(
    racer_outcome: str,
    racer_duration_seconds: int,
    ghost_row: ActionRun,
) -> bool:
    if racer_outcome not in BEAT_RACER_OUTCOMES:
        return False
    ghost_containment = _containment_seconds(ghost_row)
    if ghost_containment is None:
        return False
    return racer_duration_seconds < ghost_containment


async def maybe_record_ghost_race_beat(
    db: AsyncSession,
    *,
    ghost_opponent_run_id: str,
    racer_user_id: str,
    racer_action_run_id: str,
    racer_outcome: str,
    racer_duration_seconds: int,
) -> Optional[GhostRaceBeat]:
    ghost_row = await db.scalar(
        select(ActionRun).where(ActionRun.id == ghost_opponent_run_id)
    )
    if ghost_row is None:
        return None
    if not is_ghost_race_beat(racer_outcome, racer_duration_seconds, ghost_row):
        return None

    ghost_containment = _containment_seconds(ghost_row)
    assert ghost_containment is not None  # guarded by is_ghost_race_beat

    owner_notifications_enabled = True
    if ghost_row.user_id:
        owner = await db.scalar(select(User).where(User.id == ghost_row.user_id))
        if owner is not None:
            owner_notifications_enabled = owner.beat_notifications_enabled

    beat = GhostRaceBeat(
        racer_user_id=racer_user_id,
        racer_action_run_id=racer_action_run_id,
        ghost_action_run_id=ghost_row.id,
        ghost_owner_user_id=ghost_row.user_id,
        ghost_owner_beat_notifications_enabled=owner_notifications_enabled,
        racer_containment_seconds=racer_duration_seconds,
        ghost_containment_seconds=ghost_containment,
        beat_at=datetime.utcnow(),
    )
    db.add(beat)
    await db.flush()
    return beat
