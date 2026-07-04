"""Tests for Live Breach Events Phase 4: scheduled synchronized live arena
events.

Covers:
  - POST /admin/arena/events (admin-only creation/validation)
  - app.services.arena_event_service.transition_arena_events (the Celery
    Beat task's underlying state-machine logic — called directly against a
    real SyncSessionLocal, exactly like the task itself would, rather than
    invoking Celery's scheduler)
  - Event-scoped matchmaking queue pairing (arena_matchmaking_service.
    join_queue with event_id), including that it does NOT cross-pair with
    the ad-hoc queue or a different event's queue
  - fill_unmatched_event_queue_with_ai (AI-fallback for stragglers once an
    event's join window has closed) and join_queue's own late-join
    immediate-AI-pairing path
  - GET /arena/events/{id}/status (joined_count/matches/leaderboard shape,
    404 for unknown id)

Queue state lives on the shared, module-level `manager` singleton
(in-process, not per-test-transaction like the DB) — every test that
touches it cleans up its own entries in a `finally` block, same pattern
test_arena_matchmaking_and_leaderboard.py already uses.

The transition-task tests use `app.db.session.SyncSessionLocal` directly
(the real sync session the Celery task itself uses) rather than the
async `db` fixture, because `transition_arena_events` is a genuinely
synchronous function (Celery tasks aren't async) — mirrors how
test_arena_ai_attacker.py uses `AsyncSessionLocal` directly for the same
"talk to the real production session, not the rolled-back test
transaction" reason, with the same try/finally row cleanup convention.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.models.arena import ArenaMatch
from app.models.arena_event import ArenaEvent
from app.models.user import User
from app.services import arena_matchmaking_service
from app.services.arena_event_service import transition_arena_events
from app.websocket.manager import manager

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _second_user(db, test_org, email="second-player@example.com"):
    from app.core.security import create_access_token, hash_password

    user = User(
        email=email,
        hashed_password=hash_password("StrongPass1!"),
        full_name="Second Player",
        role="analyst",
        organization_id=test_org.id,
    )
    db.add(user)
    await db.flush()
    token = create_access_token({"sub": user.id})
    return {"token": token, "user": user}


async def _make_event(
    db,
    status="scheduled",
    seed=424242,
    archetype_key="small_healthcare",
    difficulty="hard",
    starts_at=None,
    ends_at=None,
) -> ArenaEvent:
    now = datetime.utcnow()
    event = ArenaEvent(
        title="Test Live Event",
        archetype_key=archetype_key,
        difficulty=difficulty,
        seed=seed,
        starts_at=starts_at or (now + timedelta(hours=1)),
        ends_at=ends_at or (now + timedelta(hours=2)),
        status=status,
    )
    db.add(event)
    await db.flush()
    return event


# ── Admin: create/schedule an ArenaEvent ────────────────────────────────────

async def test_create_arena_event_requires_admin(client, test_user):
    now = datetime.utcnow()
    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(test_user["token"]),
        json={
            "title": "Colonial Pipeline Live Replay",
            "archetype_key": "small_healthcare",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp.status_code == 403


async def test_create_arena_event_success(client, admin_user):
    now = datetime.utcnow()
    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Colonial Pipeline Live Replay",
            "archetype_key": "small_healthcare",
            "difficulty": "hard",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Colonial Pipeline Live Replay"
    assert data["archetype_key"] == "small_healthcare"
    assert data["difficulty"] == "hard"
    assert data["status"] == "scheduled"
    assert isinstance(data["seed"], int)
    assert data["scenario_id"] is None


async def test_create_arena_event_rejects_unknown_archetype(client, admin_user):
    now = datetime.utcnow()
    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Bad Archetype Event",
            "archetype_key": "not_a_real_archetype",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp.status_code == 400


async def test_create_arena_event_rejects_ends_at_before_starts_at(client, admin_user):
    now = datetime.utcnow()
    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Backwards Event",
            "archetype_key": "small_healthcare",
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 400


async def test_create_arena_event_accepts_tz_aware_z_suffixed_datetime_from_real_frontend(
    client, admin_user, db
):
    """The REAL frontend form (AdminDashboardPage.tsx's handleCreateEvent)
    sends `startsAtDate.toISOString()`, which is ALWAYS "Z"-suffixed —
    Pydantic v2 parses that into a tz-AWARE datetime. ArenaEvent.starts_at/
    ends_at are naive DateTime columns (no timezone=True); asyncpg rejects
    binding a tz-aware datetime into a naive column. This is the exact gap
    that let the bug through: every other test in this file builds payloads
    with naive `datetime.utcnow().isoformat()` (no "Z"), which never
    exercises this path. Confirms the endpoint both succeeds AND persists
    the correct naive-UTC instant (not shifted by a spurious tz conversion)."""
    now_utc = datetime.now(timezone.utc)
    starts_at = now_utc + timedelta(hours=1)
    ends_at = now_utc + timedelta(hours=2)

    def to_js_style_iso(dt: datetime) -> str:
        # Mirrors JS Date.prototype.toISOString()'s exact shape:
        # "YYYY-MM-DDTHH:MM:SS.sssZ".
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Z-Suffixed Frontend Payload Event",
            "archetype_key": "small_healthcare",
            "starts_at": to_js_style_iso(starts_at),
            "ends_at": to_js_style_iso(ends_at),
        },
    )
    assert resp.status_code == 201
    event_id = resp.json()["id"]

    stored = (
        await db.execute(select(ArenaEvent).where(ArenaEvent.id == event_id))
    ).scalar_one()
    assert stored.starts_at.tzinfo is None
    assert stored.ends_at.tzinfo is None
    assert abs((stored.starts_at - starts_at.replace(tzinfo=None)).total_seconds()) < 1
    assert abs((stored.ends_at - ends_at.replace(tzinfo=None)).total_seconds()) < 1


async def test_create_arena_event_rejects_non_approved_scenario(client, admin_user, db):
    from app.models.scenario import Scenario

    draft_scenario = Scenario(
        title="Draft Scenario Not Yet Approved",
        source_type="manual",
        source_reference="DRAFT-001",
        status="draft",
    )
    db.add(draft_scenario)
    await db.flush()
    await db.commit()

    now = datetime.utcnow()
    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Should Be Rejected",
            "scenario_id": draft_scenario.id,
            "archetype_key": "small_healthcare",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp.status_code == 400


async def test_create_arena_event_accepts_approved_scenario(client, admin_user, approved_scenario, db):
    now = datetime.utcnow()
    resp = await client.post(
        "/api/v1/admin/arena/events",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Should Succeed",
            "scenario_id": approved_scenario.id,
            "archetype_key": "small_healthcare",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp.status_code == 201
    assert resp.json()["scenario_id"] == approved_scenario.id


# ── Celery Beat transition task's underlying state-machine logic ───────────

async def test_transition_flips_scheduled_to_live_when_starts_at_passed():
    from app.db.session import SyncSessionLocal

    with SyncSessionLocal() as sync_db:
        now = datetime.utcnow()
        event = ArenaEvent(
            title="Should Go Live",
            archetype_key="small_healthcare",
            difficulty="medium",
            seed=1,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
            status="scheduled",
        )
        sync_db.add(event)
        sync_db.commit()
        event_id = event.id
        try:
            result = transition_arena_events(sync_db)
            assert event_id in result["transitioned_to_live"]

            refreshed = sync_db.execute(
                select(ArenaEvent).where(ArenaEvent.id == event_id)
            ).scalar_one()
            assert refreshed.status == "live"
        finally:
            sync_db.execute(delete(ArenaEvent).where(ArenaEvent.id == event_id))
            sync_db.commit()


async def test_transition_flips_live_to_completed_when_ends_at_passed():
    from app.db.session import SyncSessionLocal

    with SyncSessionLocal() as sync_db:
        now = datetime.utcnow()
        event = ArenaEvent(
            title="Should Complete",
            archetype_key="small_healthcare",
            difficulty="medium",
            seed=1,
            starts_at=now - timedelta(hours=1),
            ends_at=now - timedelta(minutes=1),
            status="live",
        )
        sync_db.add(event)
        sync_db.commit()
        event_id = event.id
        try:
            result = transition_arena_events(sync_db)
            assert event_id in result["transitioned_to_completed"]

            refreshed = sync_db.execute(
                select(ArenaEvent).where(ArenaEvent.id == event_id)
            ).scalar_one()
            assert refreshed.status == "completed"
        finally:
            sync_db.execute(delete(ArenaEvent).where(ArenaEvent.id == event_id))
            sync_db.commit()


async def test_transition_leaves_future_events_untouched():
    from app.db.session import SyncSessionLocal

    with SyncSessionLocal() as sync_db:
        now = datetime.utcnow()
        event = ArenaEvent(
            title="Future Event",
            archetype_key="small_healthcare",
            difficulty="medium",
            seed=1,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status="scheduled",
        )
        sync_db.add(event)
        sync_db.commit()
        event_id = event.id
        try:
            result = transition_arena_events(sync_db)
            assert event_id not in result["transitioned_to_live"]
            assert event_id not in result["transitioned_to_completed"]

            refreshed = sync_db.execute(
                select(ArenaEvent).where(ArenaEvent.id == event_id)
            ).scalar_one()
            assert refreshed.status == "scheduled"
        finally:
            sync_db.execute(delete(ArenaEvent).where(ArenaEvent.id == event_id))
            sync_db.commit()


async def test_transition_handles_scheduled_straight_to_completed_in_one_pass():
    """A short/overdue event whose starts_at AND ends_at have both already
    passed should reach 'completed' in a single call, not get stuck at
    'live' for one extra tick (see transition_arena_events's docstring on
    why the explicit db.flush() between passes matters here)."""
    from app.db.session import SyncSessionLocal

    with SyncSessionLocal() as sync_db:
        now = datetime.utcnow()
        event = ArenaEvent(
            title="Very Short Overdue Event",
            archetype_key="small_healthcare",
            difficulty="medium",
            seed=1,
            starts_at=now - timedelta(hours=1),
            ends_at=now - timedelta(minutes=1),
            status="scheduled",
        )
        sync_db.add(event)
        sync_db.commit()
        event_id = event.id
        try:
            result = transition_arena_events(sync_db)
            assert event_id in result["transitioned_to_live"]
            assert event_id in result["transitioned_to_completed"]

            refreshed = sync_db.execute(
                select(ArenaEvent).where(ArenaEvent.id == event_id)
            ).scalar_one()
            assert refreshed.status == "completed"
        finally:
            sync_db.execute(delete(ArenaEvent).where(ArenaEvent.id == event_id))
            sync_db.commit()


# ── Event-scoped matchmaking queue pairing ──────────────────────────────────

async def test_two_users_queued_for_same_event_get_paired_with_fixed_params(
    client, db, test_org, test_user
):
    event = await _make_event(db, seed=999999, archetype_key="small_healthcare", difficulty="hard")
    await db.commit()
    other = await _second_user(db, test_org)
    await db.commit()

    try:
        first_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert first_join.status_code == 200
        assert first_join.json()["status"] == "waiting"

        second_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(other["token"]),
        )
        assert second_join.status_code == 200
        assert second_join.json()["status"] == "matched"
        match_id = second_join.json()["match_id"]
        assert match_id is not None

        match_get = await client.get(
            f"/api/v1/arena/matches/{match_id}", headers=auth_headers(test_user["token"])
        )
        assert match_get.status_code == 200
        match_data = match_get.json()
        assert match_data["mode"] == "pvp"
        assert match_data["archetype_key"] == "small_healthcare"
        assert match_data["difficulty"] == "hard"
        assert match_data["event_id"] == event.id
        assert {match_data["attacker_user_id"], match_data["defender_user_id"]} == {
            test_user["user"].id,
            other["user"].id,
        }

        # `seed` isn't part of GET /arena/matches/{id}'s response shape
        # (_match_summary never exposed it, pre-existing / unrelated to
        # this phase) — check it directly on the persisted row instead.
        match_row = (
            await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
        ).scalar_one()
        assert match_row.seed == 999999
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other["user"].id, None)


async def test_event_queue_does_not_cross_pair_with_adhoc_queue(client, db, test_org, test_user):
    event = await _make_event(db)
    await db.commit()
    other = await _second_user(db, test_org)
    await db.commit()

    try:
        # test_user joins the ad-hoc (no event) queue.
        adhoc_join = await client.post(
            "/api/v1/arena/queue/join", headers=auth_headers(test_user["token"])
        )
        assert adhoc_join.json()["status"] == "waiting"

        # other joins the event-scoped queue.
        event_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(other["token"]),
        )
        # Must NOT be paired against the ad-hoc waiter.
        assert event_join.json()["status"] == "waiting"

        # Both remain waiting when polled.
        adhoc_status = await client.get(
            "/api/v1/arena/queue/status", headers=auth_headers(test_user["token"])
        )
        assert adhoc_status.json()["status"] == "waiting"
        event_status = await client.get(
            "/api/v1/arena/queue/status", headers=auth_headers(other["token"])
        )
        assert event_status.json()["status"] == "waiting"
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other["user"].id, None)


async def test_event_queue_does_not_cross_pair_with_different_event(client, db, test_org, test_user):
    event_a = await _make_event(db)
    await db.commit()
    event_b = await _make_event(db)
    await db.commit()
    other = await _second_user(db, test_org)
    await db.commit()

    try:
        join_a = await client.post(
            f"/api/v1/arena/queue/join?event_id={event_a.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert join_a.json()["status"] == "waiting"

        join_b = await client.post(
            f"/api/v1/arena/queue/join?event_id={event_b.id}",
            headers=auth_headers(other["token"]),
        )
        assert join_b.json()["status"] == "waiting"
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other["user"].id, None)


async def test_join_queue_unknown_event_id_is_404(client, test_user):
    resp = await client.post(
        "/api/v1/arena/queue/join?event_id=does-not-exist",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 404
    manager.arena_queue.pop(test_user["user"].id, None)


async def test_join_queue_for_event_supersedes_stale_adhoc_queue_entry(client, db, test_user):
    """A user already waiting in the ad-hoc queue (Quick Match) who then
    explicitly joins a specific event's queue must actually move into that
    event's pool — not silently stay stuck in the ad-hoc pool while the UI
    claims they're queued for the event's fixed seed/difficulty."""
    event = await _make_event(db)
    await db.commit()

    try:
        adhoc_join = await client.post(
            "/api/v1/arena/queue/join", headers=auth_headers(test_user["token"])
        )
        assert adhoc_join.json()["status"] == "waiting"
        assert manager.arena_queue[test_user["user"].id]["event_id"] is None

        event_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert event_join.status_code == 200
        assert event_join.json()["status"] == "waiting"
        # The stale ad-hoc entry must have been replaced by an event-scoped
        # one (not left as-is, not duplicated).
        assert len(manager.arena_queue) == 1
        assert manager.arena_queue[test_user["user"].id]["event_id"] == event.id
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


async def test_join_queue_idempotent_when_rejoining_same_event(client, db, test_user):
    """Re-joining the SAME event's queue (not a different pool) must stay
    idempotent — no supersession, no duplicate entry."""
    event = await _make_event(db)
    await db.commit()

    try:
        first = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        second = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert first.json()["status"] == "waiting"
        assert second.json()["status"] == "waiting"
        assert len(manager.arena_queue) == 1
        assert manager.arena_queue[test_user["user"].id]["event_id"] == event.id
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


# ── AI-fallback fill ─────────────────────────────────────────────────────────

async def test_fill_unmatched_event_queue_with_ai_pairs_lone_user_with_bot(
    client, db, test_org, test_user
):
    event = await _make_event(db, seed=13, archetype_key="small_healthcare", difficulty="easy")
    await db.commit()

    try:
        join_resp = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert join_resp.json()["status"] == "waiting"

        match_ids = await arena_matchmaking_service.fill_unmatched_event_queue_with_ai(db, event.id)
        assert len(match_ids) == 1

        status_resp = await client.get(
            "/api/v1/arena/queue/status", headers=auth_headers(test_user["token"])
        )
        assert status_resp.json()["status"] == "matched"
        assert status_resp.json()["match_id"] == match_ids[0]

        match_get = await client.get(
            f"/api/v1/arena/matches/{match_ids[0]}", headers=auth_headers(test_user["token"])
        )
        match_data = match_get.json()
        assert match_data["mode"] in ("human_defends_vs_ai", "human_attacks_vs_ai")
        assert match_data["archetype_key"] == "small_healthcare"
        assert match_data["difficulty"] == "easy"
        assert match_data["event_id"] == event.id
        # Exactly one side is the human, the other is the AI (null user id).
        human_side_count = sum(
            1 for uid in (match_data["attacker_user_id"], match_data["defender_user_id"]) if uid == test_user["user"].id
        )
        none_side_count = sum(
            1 for uid in (match_data["attacker_user_id"], match_data["defender_user_id"]) if uid is None
        )
        assert human_side_count == 1
        assert none_side_count == 1

        match_row = (
            await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_ids[0]))
        ).scalar_one()
        assert match_row.seed == 13
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


async def test_fill_unmatched_event_queue_with_ai_is_idempotent_noop_when_empty(db):
    event = await _make_event(db)
    await db.commit()

    match_ids = await arena_matchmaking_service.fill_unmatched_event_queue_with_ai(db, event.id)
    assert match_ids == []


async def test_joining_after_event_window_closed_gets_instant_ai_match(client, db, test_user):
    """join_queue's late-join path: if the event is no longer 'scheduled'
    (window already closed), a brand-new joiner is paired against an AI
    bot immediately rather than waiting on a human who will never show."""
    event = await _make_event(db, seed=77, archetype_key="small_healthcare", difficulty="medium", status="live")
    await db.commit()

    try:
        resp = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "matched"
        match_id = resp.json()["match_id"]

        match_get = await client.get(
            f"/api/v1/arena/matches/{match_id}", headers=auth_headers(test_user["token"])
        )
        match_data = match_get.json()
        assert match_data["event_id"] == event.id
        assert match_data["mode"] in ("human_defends_vs_ai", "human_attacks_vs_ai")

        match_row = (
            await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
        ).scalar_one()
        assert match_row.seed == 77
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


# ── Background sweep: "no one is left unmatched" without any client polling ─

async def test_sweep_closed_event_queues_drains_stragglers_from_closed_events(db, test_user):
    """Simulates the exact gap this fix closes: a player queued for an event
    BEFORE its window closed, the Celery Beat task later flips the event's
    status (no client ever hits GET /arena/events/{id}/status again — e.g.
    both tabs closed). Without a background sweep, this entry would sit in
    manager.arena_queue forever. sweep_closed_event_queues (called on a
    timer from app/main.py's lifespan in the real process) must find and
    drain it directly, independent of any endpoint being polled."""
    from app.services.arena_matchmaking_service import sweep_closed_event_queues

    closed_event = await _make_event(
        db, seed=321, archetype_key="small_healthcare", difficulty="medium", status="live"
    )
    still_open_event = await _make_event(db, seed=654, status="scheduled")
    await db.commit()

    other_user_id = "sweep-test-untouched-user"
    manager.arena_queue[test_user["user"].id] = {
        "joined_at": datetime.utcnow(),
        "matched_match_id": None,
        "event_id": closed_event.id,
    }
    manager.arena_queue[other_user_id] = {
        "joined_at": datetime.utcnow(),
        "matched_match_id": None,
        "event_id": still_open_event.id,
    }

    try:
        swept_event_ids = await sweep_closed_event_queues(db)
        assert closed_event.id in swept_event_ids
        assert still_open_event.id not in swept_event_ids

        # The straggler on the CLOSED event must now be matched against an AI bot.
        assert manager.arena_queue[test_user["user"].id]["matched_match_id"] is not None
        # The entry on the still-open event must be left completely untouched.
        assert manager.arena_queue[other_user_id]["matched_match_id"] is None
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other_user_id, None)


async def test_sweep_closed_event_queues_is_noop_when_nothing_queued(db):
    from app.services.arena_matchmaking_service import sweep_closed_event_queues

    # No event-scoped queue entries exist at all (any leftover ad-hoc entry
    # from another test has event_id None, which is excluded from the
    # candidate scan) — must return an empty list without erroring.
    result = await sweep_closed_event_queues(db)
    assert result == []


# ── PII: public event leaderboard must never leak a raw email address ──────

async def test_event_leaderboard_never_leaks_raw_email(client, db, test_org, test_user):
    """This route (GET /arena/events/{id}/status) has NO auth. A winner who
    never opted into a public display handle must show a generic
    placeholder, never their raw email — reusing Phase 1's opt-in
    _public_participant_label pattern instead of the `full_name or email`
    fallback that was copy-pasted in from the authenticated-only
    get_arena_leaderboard."""
    event = await _make_event(db, seed=222)
    await db.commit()
    other = await _second_user(db, test_org)
    await db.commit()

    try:
        first_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        second_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(other["token"]),
        )
        match_id = second_join.json()["match_id"]

        match_result = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
        match = match_result.scalar_one()
        now = datetime.utcnow()
        match.status = "attacker_won" if match.attacker_user_id == test_user["user"].id else "defender_won"
        match.started_at = now - timedelta(minutes=1)
        match.completed_at = now
        await db.commit()

        resp = await client.get(f"/api/v1/arena/events/{event.id}/status")
        entry = resp.json()["leaderboard"][0]
        assert entry["display_name"] != test_user["user"].email
        assert "@" not in entry["display_name"]
        assert entry["display_name"] == "Player"

        # Now opt the winner into a public handle — that should be shown instead.
        winner_row = (
            await db.execute(select(User).where(User.id == entry["user_id"]))
        ).scalar_one()
        winner_row.arena_profile_public = True
        winner_row.public_display_handle = "ShadowRunner"
        await db.commit()

        resp2 = await client.get(f"/api/v1/arena/events/{event.id}/status")
        entry2 = resp2.json()["leaderboard"][0]
        assert entry2["display_name"] == "ShadowRunner"
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other["user"].id, None)


# ── GET /arena/events (public, no-auth browse listing) ──────────────────────

async def test_list_public_arena_events_no_auth_reachable_and_shape(client, db):
    event = await _make_event(db, seed=111, status="scheduled")
    await db.commit()

    resp = await client.get("/api/v1/arena/events")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    entry = next(e for e in data if e["id"] == event.id)
    assert set(entry.keys()) == {
        "id", "title", "scenario_id", "archetype_key", "difficulty",
        "seed", "starts_at", "ends_at", "status", "created_at",
    }
    assert entry["status"] == "scheduled"
    assert entry["seed"] == 111


async def test_list_public_arena_events_status_filter(client, db):
    scheduled_event = await _make_event(db, seed=222, status="scheduled")
    cancelled_event = await _make_event(db, seed=333, status="cancelled")
    await db.commit()

    resp = await client.get("/api/v1/arena/events?status=cancelled")
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert cancelled_event.id in ids
    assert scheduled_event.id not in ids


async def test_list_public_arena_events_rejects_invalid_status_filter(client):
    resp = await client.get("/api/v1/arena/events?status=not-a-real-status")
    assert resp.status_code == 400


async def test_list_public_arena_events_does_not_leak_beyond_scenario_id_for_since_changed_scenario(
    client, db, approved_scenario
):
    """An event's scenario_id is validated approved/non-private ONLY at
    creation time (see Fix 5's scenario-approval check on POST
    /admin/arena/events). If that scenario is later edited to
    non-approved/private, this public listing must still expose nothing
    beyond the bare scenario_id already recorded on the event — never a
    nested scenario title or other detail — since arena_event_summary()
    never joins/embeds the Scenario row itself, only its id."""
    event = await _make_event(db, seed=444, status="scheduled")
    event.scenario_id = approved_scenario.id
    await db.commit()

    # Scenario is later edited to private/non-approved post-creation.
    approved_scenario.status = "draft"
    approved_scenario.is_private = True
    await db.commit()

    resp = await client.get("/api/v1/arena/events")
    assert resp.status_code == 200
    entry = next(e for e in resp.json() if e["id"] == event.id)
    assert entry["scenario_id"] == approved_scenario.id
    assert "scenario" not in entry
    assert "scenario_title" not in entry


# ── GET /arena/events/{id}/status ───────────────────────────────────────────

async def test_get_event_status_404_for_unknown_event(client):
    resp = await client.get("/api/v1/arena/events/does-not-exist/status")
    assert resp.status_code == 404


async def test_get_event_status_returns_expected_shape(client, db, test_org, test_user):
    event = await _make_event(db, seed=55, archetype_key="small_healthcare", difficulty="medium")
    await db.commit()
    other = await _second_user(db, test_org)
    await db.commit()

    try:
        # Pair the two into a real event match, then mark it decisively won
        # so the leaderboard has something to show.
        first_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        second_join = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(other["token"]),
        )
        match_id = second_join.json()["match_id"]

        match_result = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
        match = match_result.scalar_one()
        now = datetime.utcnow()
        match.status = "attacker_won"
        match.started_at = now - timedelta(minutes=5)
        match.completed_at = now
        await db.commit()

        resp = await client.get(f"/api/v1/arena/events/{event.id}/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["event"]["id"] == event.id
        assert data["event"]["status"] == "scheduled"
        assert data["joined_count"] == 2
        assert len(data["matches"]) == 1
        assert data["matches"][0]["id"] == match_id

        assert len(data["leaderboard"]) == 1
        entry = data["leaderboard"][0]
        assert entry["match_id"] == match_id
        assert entry["won"] is True
        assert entry["winner_role"] == "attacker"
        assert entry["user_id"] == match.attacker_user_id
        assert entry["resolution_seconds"] == pytest.approx(300, abs=2)
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other["user"].id, None)


async def test_get_event_status_drains_ai_fallback_when_window_closed(
    client, db, test_org, test_user
):
    """Polling the status endpoint for an event whose window has already
    closed should opportunistically drain any still-waiting queue entry
    into an AI match (this is the in-process trigger point documented in
    arena_event_service.py, since a Celery worker process can't see
    manager.arena_queue)."""
    event = await _make_event(db, seed=88, archetype_key="small_healthcare", difficulty="medium", status="scheduled")
    await db.commit()

    try:
        join_resp = await client.post(
            f"/api/v1/arena/queue/join?event_id={event.id}",
            headers=auth_headers(test_user["token"]),
        )
        assert join_resp.json()["status"] == "waiting"

        # Simulate the Celery Beat task having flipped the event live.
        event_result = await db.execute(select(ArenaEvent).where(ArenaEvent.id == event.id))
        live_event = event_result.scalar_one()
        live_event.status = "live"
        await db.commit()

        resp = await client.get(f"/api/v1/arena/events/{event.id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["matches"]) == 1
        assert data["matches"][0]["mode"] in ("human_defends_vs_ai", "human_attacks_vs_ai")
        assert data["joined_count"] == 1
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
