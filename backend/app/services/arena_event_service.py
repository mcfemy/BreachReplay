"""Live Breach Events Phase 4 — scheduled synchronized live arena events.

Owns:
  - `arena_event_summary(event)`, the shared serializer used by both the
    admin creation route (app/api/routes/admin.py) and the public event
    status route (app/api/routes/arena.py) — kept in one place so the two
    don't drift, the same duplication mistake a Phase 3 review already
    caught once for `_COMPLETED_STATUSES`.
  - `transition_arena_events(db)` / `transition_arena_events_task`, the
    ArenaEvent state machine: scheduled -> live at `starts_at`, live ->
    completed at `ends_at`. Registered as a Celery Beat task running every
    60 seconds (see app/pipeline/celery_app.py's beat_schedule + include
    list).

IMPORTANT — what this module deliberately does NOT do: trigger the
AI-fallback-fill behavior (pairing any still-unmatched queued player
against an AI bot once an event's join window closes). The plan's own
framing suggested doing that from this same Celery Beat task, but this
codebase's docker-compose topology makes that incorrect: `backend`
(uvicorn) and `worker`/`beat` (Celery) are SEPARATE OS PROCESSES. The
matchmaking queue (`app.websocket.manager.manager.arena_queue`) is
in-process, in-memory state that belongs to the `backend` process only
(see manager.py's own docstring on why that's a deliberate choice) — a
Celery task running in the `worker`/`beat` container would only ever see
its own process's fresh, empty `ConnectionManager` instance, never the
real one. Calling the fallback from here would silently no-op forever,
which is worse than not calling it at all.

So: `transition_arena_events` only ever flips the DB status column (safe
from any process). The actual AI-fallback-fill
(`arena_matchmaking_service.fill_unmatched_event_queue_with_ai`) is invoked
from inside the `backend` process instead, at the two points that
naturally run there:
  1. `arena_matchmaking_service.join_queue`'s late-join path — a player who
     joins for an event whose window has already closed gets an AI
     opponent immediately, no waiting.
  2. `GET /arena/events/{id}/status` (app/api/routes/arena.py) — the plan's
     own frontend convention has clients poll this exact endpoint while an
     event is live/just-closed, so each poll opportunistically drains any
     still-unmatched queue entries left over from players who joined
     *before* the window closed but never got a human opponent. No-op once
     that event's queue is already empty.

"The window closes" is interpreted as: the moment `starts_at` passes (i.e.
the scheduled -> live transition), NOT `ends_at`. Waiting until `ends_at`
(which could be hours later) to give a queued player an AI opponent would
leave them stuck on a "waiting for a human" screen for the entire event —
bad UX, and pointless since after the official start time new human
arrivals are vanishingly unlikely to still be queuing for the SAME event
rather than already playing. `event.status != "scheduled"` (i.e. live or
completed) is used as the "window closed" check everywhere in this phase.
"""
from datetime import datetime

from sqlalchemy import select

from app.db.session import SyncSessionLocal
from app.models.arena_event import ArenaEvent
from app.pipeline.celery_app import celery_app


def arena_event_summary(event: ArenaEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "scenario_id": event.scenario_id,
        "archetype_key": event.archetype_key,
        "difficulty": event.difficulty,
        "seed": event.seed,
        "starts_at": event.starts_at.isoformat() if event.starts_at else None,
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "status": event.status,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def transition_arena_events(db) -> dict:
    """Given a SYNC db session (SyncSessionLocal — Celery tasks are not
    async), advance every ArenaEvent's status:
      - scheduled -> live,     for events whose starts_at <= now
      - live      -> completed, for events whose ends_at <= now

    A `db.flush()` happens between the two passes so a very short event
    (starts_at AND ends_at both already <= now on the same tick, e.g. a
    test fixture or an admin-scheduled 1-minute event) can go straight from
    scheduled to completed within a single invocation, rather than sitting
    at "live" for one extra ~60s tick before the next run notices ends_at
    has also passed (SyncSessionLocal is created with autoflush=False, so
    without the explicit flush the second SELECT below would still see the
    pre-transition "scheduled" status in the database).

    Returns a small dict of transitioned event ids — useful for tests and
    for logging what the beat task actually did on a given run.
    """
    now = datetime.utcnow()

    newly_live = db.execute(
        select(ArenaEvent).where(ArenaEvent.status == "scheduled", ArenaEvent.starts_at <= now)
    ).scalars().all()
    for event in newly_live:
        event.status = "live"
    db.flush()

    newly_completed = db.execute(
        select(ArenaEvent).where(ArenaEvent.status == "live", ArenaEvent.ends_at <= now)
    ).scalars().all()
    for event in newly_completed:
        event.status = "completed"

    db.commit()

    return {
        "transitioned_to_live": [e.id for e in newly_live],
        "transitioned_to_completed": [e.id for e in newly_completed],
    }


@celery_app.task(bind=True, name="app.services.arena_event_service.transition_arena_events_task")
def transition_arena_events_task(self):
    with SyncSessionLocal() as db:
        return transition_arena_events(db)
