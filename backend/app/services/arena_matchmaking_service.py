"""Matchmaking queue for Live Arena Mode Phase I — pairs two waiting humans
into a fresh PvP match. Queue state itself lives in-process
(`manager.arena_queue`, guarded by `manager._arena_queue_lock`) — see the
comment on that dict for why this doesn't need a DB table. Match creation,
once a pair is found, DOES go through the real `ArenaMatch` row exactly
like `POST /arena/matches` does, so a queue-paired match behaves identically
to a manually-created one from that point on.
"""
import secrets
import uuid
from datetime import datetime

from app.models.arena import ArenaMatch
from app.services.org_simulation import ORG_ARCHETYPES

# Simple wait-time heuristic: if someone else is already waiting, a match is
# imminent (they'll likely pair on this very call); otherwise give a
# friendly, honestly-labeled placeholder rather than a fake precise number.
_ESTIMATED_WAIT_SECONDS_WITH_OTHERS_WAITING = 10
_ESTIMATED_WAIT_SECONDS_ALONE = 60


async def join_queue(db, user_id: str) -> dict:
    """Add `user_id` to the matchmaking queue (idempotent — re-joining while
    already queued or already matched just returns the current state, it
    does not create a second entry), then try to pair with the
    longest-waiting other queued user. Returns the same shape as
    `queue_status`."""
    from app.websocket.manager import manager

    async with manager._arena_queue_lock:
        existing = manager.arena_queue.get(user_id)
        if existing is not None:
            return await _status_locked(user_id)

        manager.arena_queue[user_id] = {"joined_at": datetime.utcnow(), "matched_match_id": None}

        # Longest-waiting other unmatched entry — simple FIFO pairing.
        opponent_id = None
        opponent_joined_at = None
        for candidate_id, entry in manager.arena_queue.items():
            if candidate_id == user_id or entry["matched_match_id"] is not None:
                continue
            if opponent_joined_at is None or entry["joined_at"] < opponent_joined_at:
                opponent_id = candidate_id
                opponent_joined_at = entry["joined_at"]

        if opponent_id is not None:
            # Randomize which side is attacker vs defender so queue order
            # doesn't determine role — non-deterministic choice is fine
            # here (match SETUP, not anything inside org_simulation.py's
            # pure functions).
            if secrets.randbelow(2) == 0:
                attacker_id, defender_id = user_id, opponent_id
            else:
                attacker_id, defender_id = opponent_id, user_id

            seed = secrets.randbelow(2**31 - 1)
            archetype_key = secrets.choice(list(ORG_ARCHETYPES.keys()))
            match = ArenaMatch(
                id=str(uuid.uuid4()),
                seed=seed,
                archetype_key=archetype_key,
                mode="pvp",
                attacker_user_id=attacker_id,
                defender_user_id=defender_id,
                difficulty="medium",
                status="lobby",
                created_at=datetime.utcnow(),
            )
            db.add(match)
            await db.commit()

            manager.arena_queue[user_id]["matched_match_id"] = match.id
            manager.arena_queue[opponent_id]["matched_match_id"] = match.id

        return await _status_locked(user_id)


async def queue_status(user_id: str) -> dict:
    """Poll the current queue state for `user_id`. If a match was found,
    this CONSUMES the queue entry (pops it) so the same match isn't handed
    back twice — the caller is expected to navigate to the match once
    `status == "matched"`."""
    from app.websocket.manager import manager

    async with manager._arena_queue_lock:
        return await _status_locked(user_id)


async def _status_locked(user_id: str) -> dict:
    """Caller MUST already hold manager._arena_queue_lock."""
    from app.websocket.manager import manager

    entry = manager.arena_queue.get(user_id)
    if entry is None:
        return {"status": "not_queued", "match_id": None, "estimated_wait_seconds": None}

    if entry["matched_match_id"] is not None:
        match_id = entry["matched_match_id"]
        manager.arena_queue.pop(user_id, None)
        return {"status": "matched", "match_id": match_id, "estimated_wait_seconds": 0}

    others_waiting = any(
        other_id != user_id and other_entry["matched_match_id"] is None
        for other_id, other_entry in manager.arena_queue.items()
    )
    estimated_wait = (
        _ESTIMATED_WAIT_SECONDS_WITH_OTHERS_WAITING if others_waiting
        else _ESTIMATED_WAIT_SECONDS_ALONE
    )
    return {"status": "waiting", "match_id": None, "estimated_wait_seconds": estimated_wait}


async def leave_queue(user_id: str) -> bool:
    """Remove `user_id` from the queue if present and not yet matched.
    Returns True if an entry was actually removed. A user who has already
    been matched can't "leave" via this — the match itself exists now,
    canceling it would be the normal abandon-a-match path, not this."""
    from app.websocket.manager import manager

    async with manager._arena_queue_lock:
        entry = manager.arena_queue.get(user_id)
        if entry is None or entry["matched_match_id"] is not None:
            return False
        del manager.arena_queue[user_id]
        return True
