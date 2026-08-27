"""Per-user Incident Response Index — ghost-race progression only.

Intentionally separate from arena_rating / arena_rating_service.compute_new_ratings.
The public GET /arena/public/stats/global-index endpoint is a cohort aggregate
from ArenaMatch rows and is unchanged by this field.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

RESPONSE_INDEX_DEFAULT = 1200
RESPONSE_INDEX_BEAT_BUMP = 15


async def bump_response_index_for_ghost_beat(
    db: AsyncSession,
    racer_user_id: str,
) -> tuple[int, int]:
    """Apply a fixed bump when the racer records a GhostRaceBeat.

    Returns (bump_amount, new_response_index). Caller must be inside the same
    transaction as beat insert — no separate commit here.
    """
    racer = await db.scalar(select(User).where(User.id == racer_user_id))
    if racer is None:
        return 0, RESPONSE_INDEX_DEFAULT
    racer.response_index += RESPONSE_INDEX_BEAT_BUMP
    await db.flush()
    return RESPONSE_INDEX_BEAT_BUMP, racer.response_index
