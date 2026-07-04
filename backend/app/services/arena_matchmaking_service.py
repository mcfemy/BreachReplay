"""Matchmaking queue for Live Arena Mode Phase I — pairs two waiting humans
into a fresh PvP match. Queue state itself lives in-process
(`manager.arena_queue`, guarded by `manager._arena_queue_lock`) — see the
comment on that dict for why this doesn't need a DB table. Match creation,
once a pair is found, DOES go through the real `ArenaMatch` row exactly
like `POST /arena/matches` does, so a queue-paired match behaves identically
to a manually-created one from that point on.

Live Breach Events Phase 4 extends this with an optional `event_id`:
`manager.arena_queue` now stores an `event_id` key (`None` for the
ad-hoc/ordinary queue) on every entry, and pairing only ever matches
entries whose `event_id` is EQUAL — the ad-hoc pool and each event's pool
are disjoint, coexisting in the same dict without cross-pairing. When
`event_id` is given, the resulting match's seed/archetype_key/difficulty
come from the ArenaEvent (fixed/synchronized), not `secrets.randbelow`/
`secrets.choice`, and the match's `event_id` column is set.

See `fill_unmatched_event_queue_with_ai` below and
`app/services/arena_event_service.py`'s module docstring for the
AI-fallback design (what "the join window closes" means here, and why that
fallback can only correctly run in this process, never from the Celery
Beat task).
"""
import secrets
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.models.arena import ArenaMatch
from app.models.arena_event import ArenaEvent
from app.services.org_simulation import ORG_ARCHETYPES

# Simple wait-time heuristic: if someone else is already waiting, a match is
# imminent (they'll likely pair on this very call); otherwise give a
# friendly, honestly-labeled placeholder rather than a fake precise number.
_ESTIMATED_WAIT_SECONDS_WITH_OTHERS_WAITING = 10
_ESTIMATED_WAIT_SECONDS_ALONE = 60


class EventNotFoundError(Exception):
    """Raised by join_queue when a caller-supplied event_id doesn't exist."""


class EventNotJoinableError(Exception):
    """Raised by join_queue when the event exists but has been cancelled."""


async def _load_event(db, event_id: str) -> ArenaEvent:
    result = await db.execute(select(ArenaEvent).where(ArenaEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise EventNotFoundError(f"Arena event {event_id} not found")
    if event.status == "cancelled":
        raise EventNotJoinableError(f"Arena event {event_id} has been cancelled")
    return event


async def _pair_with_ai_bot_locked(db, user_id: str, event: ArenaEvent) -> str:
    """Create an AI-opponent ArenaMatch for `user_id` at `event`'s fixed
    seed/archetype_key/difficulty, and mark their queue entry matched.

    Caller MUST already hold `manager._arena_queue_lock`. Attacker/defender
    role is a random 50/50 per player (same non-deterministic-is-fine
    reasoning as the human-vs-human pairing above) — this does NOT invent
    new bot-policy code: any match with a null attacker_user_id or null
    defender_user_id already activates the existing Phase D/E AI
    attacker/defender bots purely from `ArenaMatch.mode`
    (human_defends_vs_ai / human_attacks_vs_ai) once a WS connection opens
    for it — see `_maybe_start_arena_attacker_bot` /
    `_apply_defender_bot_response_locked` in app/websocket/handlers.py.

    Returns the new match's id.
    """
    from app.websocket.manager import manager

    if secrets.randbelow(2) == 0:
        mode = "human_defends_vs_ai"
        attacker_user_id, defender_user_id = None, user_id
    else:
        mode = "human_attacks_vs_ai"
        attacker_user_id, defender_user_id = user_id, None

    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=event.seed,
        archetype_key=event.archetype_key,
        mode=mode,
        attacker_user_id=attacker_user_id,
        defender_user_id=defender_user_id,
        difficulty=event.difficulty,
        status="lobby",
        event_id=event.id,
        created_at=datetime.utcnow(),
    )
    db.add(match)
    await db.commit()

    manager.arena_queue[user_id]["matched_match_id"] = match.id
    return match.id


async def join_queue(db, user_id: str, event_id: Optional[str] = None) -> dict:
    """Add `user_id` to the matchmaking queue (idempotent — re-joining while
    already queued or already matched just returns the current state, it
    does not create a second entry), then try to pair with the
    longest-waiting other queued user IN THE SAME POOL (ad-hoc when
    `event_id` is None, or the same event's pool when given). Returns the
    same shape as `queue_status`.

    Raises `EventNotFoundError` / `EventNotJoinableError` if `event_id` is
    given but invalid — callers (see POST /arena/queue/join in
    app/api/routes/arena.py) translate these into 404 / 400 respectively.

    If `event_id` is given and that event's join window has ALREADY closed
    (`event.status != "scheduled"` — see arena_event_service.py's docstring
    for why that's the chosen definition of "closed"), this player is
    joining too late to ever meet a human in this event's pool: they're
    paired against an AI bot immediately rather than left waiting on
    someone who will never show up.
    """
    from app.websocket.manager import manager

    event: Optional[ArenaEvent] = None
    if event_id is not None:
        event = await _load_event(db, event_id)

    async with manager._arena_queue_lock:
        existing = manager.arena_queue.get(user_id)
        if existing is not None:
            if existing.get("event_id") == event_id or existing["matched_match_id"] is not None:
                # Already queued for this exact pool, or already resolved
                # into a real match — idempotent, just report current state.
                return await _status_locked(user_id)
            # Still genuinely waiting, but in a DIFFERENT pool than this
            # explicit new join request (e.g. was in the ad-hoc queue, now
            # asking to join a specific event's queue). The new request
            # supersedes the stale entry — equivalent to the caller calling
            # leave_queue() then join_queue() again — rather than silently
            # leaving them stuck in the wrong pool.
            del manager.arena_queue[user_id]

        manager.arena_queue[user_id] = {
            "joined_at": datetime.utcnow(),
            "matched_match_id": None,
            "event_id": event_id,
        }

        if event is not None and event.status != "scheduled":
            await _pair_with_ai_bot_locked(db, user_id, event)
            return await _status_locked(user_id)

        # Longest-waiting other unmatched entry in the SAME pool
        # (event_id must match exactly, including None == None for the
        # ad-hoc pool) — simple FIFO pairing.
        opponent_id = None
        opponent_joined_at = None
        for candidate_id, entry in manager.arena_queue.items():
            if candidate_id == user_id or entry["matched_match_id"] is not None:
                continue
            if entry.get("event_id") != event_id:
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

            if event is not None:
                # Fixed/synchronized: every match paired under this event
                # plays the identical seed/archetype/difficulty.
                seed = event.seed
                archetype_key = event.archetype_key
                difficulty = event.difficulty
            else:
                seed = secrets.randbelow(2**31 - 1)
                archetype_key = secrets.choice(list(ORG_ARCHETYPES.keys()))
                difficulty = "medium"

            match = ArenaMatch(
                id=str(uuid.uuid4()),
                seed=seed,
                archetype_key=archetype_key,
                mode="pvp",
                attacker_user_id=attacker_id,
                defender_user_id=defender_id,
                difficulty=difficulty,
                status="lobby",
                event_id=event_id,
                created_at=datetime.utcnow(),
            )
            db.add(match)
            await db.commit()

            manager.arena_queue[user_id]["matched_match_id"] = match.id
            manager.arena_queue[opponent_id]["matched_match_id"] = match.id

        return await _status_locked(user_id)


async def fill_unmatched_event_queue_with_ai(db, event_id: str) -> list[str]:
    """Pair every still-unmatched queue entry for `event_id` against an AI
    bot opponent, at that event's fixed seed/archetype_key/difficulty.

    Intended to run once an event's join window has closed
    (`event.status != "scheduled"`), so a human who queued for this event
    BEFORE the window closed but never got paired with another human isn't
    left waiting forever — "no one is left unmatched" per the phase plan.

    Idempotent / safe to call repeatedly for the same event_id: once an
    entry is matched, it's excluded from the scan (`matched_match_id is not
    None`), so a second call after the first has drained the pool is just a
    fast no-op.

    PROCESS LOCALITY — read before calling this from anywhere new: this
    function mutates `manager.arena_queue`, in-process state owned by the
    `backend` (uvicorn) container. It must only ever be called from code
    running in that same process (currently: `join_queue`'s late-join path
    above, `GET /arena/events/{id}/status` in app/api/routes/arena.py, and
    `sweep_closed_event_queues` below) — NEVER from the Celery `worker`/
    `beat` containers, which are separate OS processes with their own empty
    `ConnectionManager` instance. See
    app/services/arena_event_service.py's module docstring for the full
    reasoning.

    Returns the list of newly-created match ids (empty if nothing was
    waiting, or if `event_id` doesn't exist).
    """
    from app.websocket.manager import manager

    event_result = await db.execute(select(ArenaEvent).where(ArenaEvent.id == event_id))
    event = event_result.scalar_one_or_none()
    if event is None:
        return []

    matched_ids: list[str] = []
    async with manager._arena_queue_lock:
        waiting_user_ids = [
            uid
            for uid, entry in manager.arena_queue.items()
            if entry.get("event_id") == event_id and entry["matched_match_id"] is None
        ]
        for uid in waiting_user_ids:
            match_id = await _pair_with_ai_bot_locked(db, uid, event)
            matched_ids.append(match_id)

    return matched_ids


async def sweep_closed_event_queues(db) -> list[str]:
    """Find every event_id currently represented in `manager.arena_queue` by
    at least one still-unmatched entry, whose event's join window has
    already closed (`status != "scheduled"`), and drain each one via
    `fill_unmatched_event_queue_with_ai`.

    This is the core "no one is left unmatched" logic behind the `backend`
    process's background sweep loop (see app/main.py's lifespan, which calls
    this on a timer). Without it, the guarantee only held if a client
    happened to keep polling `GET /arena/events/{id}/status` after an
    event's window closed — two players who queued for an event, never got
    paired with a human, and then closed their browser tabs would otherwise
    sit in `manager.arena_queue` forever (in-process memory, lost entirely
    on a backend restart). This function makes the guarantee hold
    unconditionally, still without needing any cross-process coordination
    (see fill_unmatched_event_queue_with_ai's PROCESS LOCALITY note above —
    same constraint applies here).

    Safe/idempotent to call repeatedly (e.g. every tick of a timer loop):
    `fill_unmatched_event_queue_with_ai` already excludes already-matched
    entries, and an event_id with no unmatched entries left is simply not
    returned by the query below.

    Returns the list of distinct event_ids that were found closed-with-
    stragglers and swept this call (not necessarily that anyone was
    actually still unmatched by the time the per-event drain ran — just
    that a drain was attempted).
    """
    from app.websocket.manager import manager

    async with manager._arena_queue_lock:
        candidate_event_ids = {
            entry["event_id"]
            for entry in manager.arena_queue.values()
            if entry.get("event_id") is not None and entry["matched_match_id"] is None
        }

    if not candidate_event_ids:
        return []

    result = await db.execute(
        select(ArenaEvent.id).where(
            ArenaEvent.id.in_(candidate_event_ids),
            ArenaEvent.status != "scheduled",
        )
    )
    closed_event_ids = [row[0] for row in result.all()]

    for event_id in closed_event_ids:
        await fill_unmatched_event_queue_with_ai(db, event_id)

    return closed_event_ids


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

    # Scoped to the SAME pool as this entry (event_id must match, including
    # None == None for the ad-hoc pool) — Phase 4 introduced multiple
    # disjoint pools sharing this one dict, and an "others waiting" signal
    # from a different event's pool would never actually pair with this
    # user, so it must not feed this estimate.
    this_event_id = entry.get("event_id")
    others_waiting = any(
        other_id != user_id
        and other_entry["matched_match_id"] is None
        and other_entry.get("event_id") == this_event_id
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
