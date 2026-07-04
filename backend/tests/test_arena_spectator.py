"""Tests for Live Breach Events Phase 5: spectator mode (the final phase of
this initiative, depends on Phase 4's ArenaEvent/event_id).

Covers:
  - manager.py: register_arena_spectator/unregister_arena_spectator/
    broadcast_to_arena_spectators/arena_spectator_count, including the
    "safe no-op with zero spectators" invariant _notify_arena_action_result
    now relies on for every single arena action.
  - app.websocket.handlers.arena_spectator_ws_handler: hard-rejects a match
    with event_id is None (even though nothing in the test's inbound frame
    claims otherwise — the gate is server-side, re-derived from the DB, and
    runs before any message is even read), connects successfully and sends
    a redacted `spectator_init` snapshot for a real event-scoped match, and
    silently ignores/rejects an attacker_action sent over the spectator
    socket (never reaches _execute_arena_action / never persists an
    ArenaAction row).
  - GET /arena/events/{id}/live-matches: only currently-active matches for
    that event, no auth required, 404 for an unknown event id.

WS-handler testing convention: per test_arena.py's documented finding,
starlette's TestClient.websocket_connect is incompatible with this suite's
fakeredis-per-event-loop fixture, so arena_ws_handler-family functions are
already tested by calling them directly rather than through a real ASGI
transport. arena_spectator_ws_handler takes a plain `websocket: WebSocket`
argument and only ever calls `.send_json`/`.receive_text`/`.close` on it
(never anything ASGI-transport-specific), so a minimal FakeWebSocket double
implementing exactly those three methods is sufficient here — no new test
harness invented, this is the same "call the handler function directly"
approach test_arena_ai_attacker.py's _execute_arena_action tests use, just
extended one level further (a fake transport object) since this handler's
argument IS the transport rather than a match_id/user_id pair.

Uses `app.db.session.AsyncSessionLocal` directly (not the `db`/`test_org`
fixtures) for anything arena_spectator_ws_handler itself will read, exactly
per test_arena_ai_attacker.py's documented reasoning: that handler opens its
own AsyncSessionLocal() session internally, which is a different
connection/pool than the `db` fixture's single rolled-back transaction —
writes made only through `db` are invisible to it. REST-only tests (the
live-matches endpoint) use the normal `client`/`db` fixtures, matching every
other arena REST test in this suite.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import delete, select

from app.models.arena import ArenaMatch, ArenaAction
from app.models.arena_event import ArenaEvent
from app.websocket.handlers import arena_spectator_ws_handler
from app.websocket.manager import manager

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    """Minimal double for starlette's WebSocket implementing only the
    methods arena_spectator_ws_handler actually calls. See module
    docstring for why this is the right level of fake given this
    codebase's existing WS-testing constraints."""

    def __init__(self, incoming: list | None = None):
        self.sent: list[dict] = []
        self.closed_code: int | None = None
        self._incoming = list(incoming or [])

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive_text(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


async def _make_event(seed=13579, archetype_key="small_healthcare", difficulty="medium", status="live"):
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        event = ArenaEvent(
            id=str(uuid.uuid4()),
            title="Spectator Test Event",
            archetype_key=archetype_key,
            difficulty=difficulty,
            seed=seed,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
            status=status,
        )
        db.add(event)
        await db.commit()
        return event.id


async def _make_match(event_id, status="active", seed=24680, archetype_key="small_healthcare"):
    from app.db.session import AsyncSessionLocal

    match_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        match = ArenaMatch(
            id=match_id,
            seed=seed,
            archetype_key=archetype_key,
            mode="pvp",
            attacker_user_id=None,
            defender_user_id=None,
            status=status,
            event_id=event_id,
            started_at=datetime.utcnow() if status == "active" else None,
        )
        db.add(match)
        await db.commit()
    return match_id


async def _cleanup_match(match_id):
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        await db.commit()


async def _cleanup_event(event_id):
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaEvent).where(ArenaEvent.id == event_id))
        await db.commit()


# ── 1. manager.py: arena_spectators bookkeeping ─────────────────────────────

async def test_broadcast_to_arena_spectators_is_safe_noop_with_zero_spectators():
    """The overwhelmingly common case: _notify_arena_action_result now calls
    this unconditionally for every action on every match. Must never raise,
    must never create a phantom entry in manager.arena_spectators."""
    match_id = f"no-spectators-{uuid.uuid4().hex[:8]}"
    assert match_id not in manager.arena_spectators
    await manager.broadcast_to_arena_spectators(match_id, {"type": "spectator_action"})
    assert match_id not in manager.arena_spectators
    assert manager.arena_spectator_count(match_id) == 0


async def test_register_unregister_and_broadcast_arena_spectators():
    match_id = f"spectator-manager-{uuid.uuid4().hex[:8]}"
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    manager.register_arena_spectator(match_id, ws1)
    manager.register_arena_spectator(match_id, ws2)
    assert manager.arena_spectator_count(match_id) == 2

    await manager.broadcast_to_arena_spectators(match_id, {"type": "spectator_action", "sequence_number": 0})
    assert ws1.sent == [{"type": "spectator_action", "sequence_number": 0}]
    assert ws2.sent == [{"type": "spectator_action", "sequence_number": 0}]

    manager.unregister_arena_spectator(match_id, ws1)
    assert manager.arena_spectator_count(match_id) == 1

    manager.unregister_arena_spectator(match_id, ws2)
    assert manager.arena_spectator_count(match_id) == 0
    # Empty set is dropped entirely (mirrors arena_connections' cleanup).
    assert match_id not in manager.arena_spectators


async def test_broadcast_to_arena_spectators_cleans_up_dead_sockets():
    match_id = f"spectator-dead-socket-{uuid.uuid4().hex[:8]}"

    class DeadWebSocket:
        async def send_json(self, message):
            raise RuntimeError("connection closed")

    alive = FakeWebSocket()
    dead = DeadWebSocket()
    manager.register_arena_spectator(match_id, alive)
    manager.register_arena_spectator(match_id, dead)

    await manager.broadcast_to_arena_spectators(match_id, {"type": "spectator_action"})

    assert alive.sent == [{"type": "spectator_action"}]
    assert manager.arena_spectator_count(match_id) == 1
    manager.unregister_arena_spectator(match_id, alive)
    assert match_id not in manager.arena_spectators


# ── 2. arena_spectator_ws_handler: hard gate on match.event_id ──────────────

async def test_spectator_ws_rejected_for_match_with_no_event_id():
    """Even though nothing about the client's connection claims otherwise
    (there's no client-side "I am event-scoped" flag to spoof in the first
    place), a match with event_id is None must be hard-rejected — this is
    the one invariant the whole phase depends on for avoiding the general
    private-match consent problem."""
    match_id = await _make_match(event_id=None, status="active")
    try:
        ws = FakeWebSocket()
        await arena_spectator_ws_handler(ws, match_id)
        assert ws.closed_code == 4003
        assert ws.sent == []
        assert manager.arena_spectator_count(match_id) == 0
    finally:
        await _cleanup_match(match_id)


async def test_spectator_ws_rejected_for_unknown_match():
    ws = FakeWebSocket()
    await arena_spectator_ws_handler(ws, "does-not-exist-at-all")
    assert ws.closed_code == 4004
    assert ws.sent == []


# ── 3. arena_spectator_ws_handler: happy path + redacted initial view ──────

async def test_spectator_ws_connects_and_receives_redacted_initial_view():
    event_id = await _make_event()
    match_id = await _make_match(event_id=event_id, status="active")
    try:
        ws = FakeWebSocket(incoming=[])  # no inbound messages -> disconnects immediately
        await arena_spectator_ws_handler(ws, match_id)

        assert ws.closed_code is None  # never explicitly closed by the handler itself
        assert len(ws.sent) == 1
        init_event = ws.sent[0]
        assert init_event["type"] == "spectator_init"
        assert init_event["match"]["id"] == match_id
        assert init_event["match"]["event_id"] == event_id

        state_view = init_event["state"]
        # Redacted-less-than-either-participant-view shape: coarse segment/
        # host counts only, no host list, no credentials, no CVEs, no
        # per-segment monitored flags.
        assert set(state_view.keys()) == {"segment_count", "segments", "host_count"}
        assert state_view["segment_count"] == len(state_view["segments"])
        assert all(set(seg.keys()) == {"id", "name"} for seg in state_view["segments"])
        assert isinstance(state_view["host_count"], int) and state_view["host_count"] > 0

        # Must have unregistered itself on disconnect.
        assert manager.arena_spectator_count(match_id) == 0
    finally:
        await _cleanup_match(match_id)
        await _cleanup_event(event_id)


# ── 4. A spectator cannot submit real game actions ──────────────────────────

async def test_spectator_ws_ignores_attacker_action_message():
    import json

    event_id = await _make_event()
    match_id = await _make_match(event_id=event_id, status="active")
    try:
        forged_action = json.dumps({
            "type": "attacker_action",
            "action_type": "gain_foothold",
            "payload": {"host_id": "whatever"},
        })
        ws = FakeWebSocket(incoming=[forged_action])
        await arena_spectator_ws_handler(ws, match_id)

        # No error frame, no action_result — the message is silently
        # ignored, never routed to _execute_arena_action.
        sent_types = [m.get("type") for m in ws.sent]
        assert "action_result" not in sent_types
        assert "error" not in sent_types

        # Confirm nothing was actually persisted for this match.
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(select(ArenaAction).where(ArenaAction.match_id == match_id))
            ).scalars().all()
        assert rows == []
    finally:
        await _cleanup_match(match_id)
        await _cleanup_event(event_id)


async def test_spectator_ws_answers_ping():
    event_id = await _make_event()
    match_id = await _make_match(event_id=event_id, status="active")
    try:
        import json
        ws = FakeWebSocket(incoming=[json.dumps({"type": "ping"})])
        await arena_spectator_ws_handler(ws, match_id)

        pong_events = [m for m in ws.sent if m.get("type") == "pong"]
        assert len(pong_events) == 1
    finally:
        await _cleanup_match(match_id)
        await _cleanup_event(event_id)


# ── 5. GET /arena/events/{id}/live-matches ──────────────────────────────────

async def test_live_matches_returns_only_active_matches_no_auth(client, db):
    now = datetime.utcnow()
    event = ArenaEvent(
        title="Live Matches REST Test",
        archetype_key="small_healthcare",
        difficulty="medium",
        seed=42,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        status="live",
    )
    db.add(event)
    await db.flush()

    active_match = ArenaMatch(
        id=str(uuid.uuid4()), seed=1, archetype_key="small_healthcare", mode="pvp",
        status="active", event_id=event.id, started_at=now,
    )
    lobby_match = ArenaMatch(
        id=str(uuid.uuid4()), seed=2, archetype_key="small_healthcare", mode="pvp",
        status="lobby", event_id=event.id,
    )
    completed_match = ArenaMatch(
        id=str(uuid.uuid4()), seed=3, archetype_key="small_healthcare", mode="pvp",
        status="attacker_won", event_id=event.id, started_at=now, completed_at=now,
    )
    db.add_all([active_match, lobby_match, completed_match])
    await db.commit()

    # No Authorization header at all -- confirms this route is genuinely
    # reachable unauthenticated.
    resp = await client.get(f"/api/v1/arena/events/{event.id}/live-matches")
    assert resp.status_code == 200
    data = resp.json()
    ids = [m["id"] for m in data]
    assert active_match.id in ids
    assert lobby_match.id not in ids
    assert completed_match.id not in ids

    entry = next(m for m in data if m["id"] == active_match.id)
    assert entry["spectator_count"] == 0
    assert entry["event_id"] == event.id


async def test_live_matches_unknown_event_404(client):
    resp = await client.get("/api/v1/arena/events/does-not-exist/live-matches")
    assert resp.status_code == 404


async def test_live_matches_reflects_spectator_count(client, db):
    now = datetime.utcnow()
    event = ArenaEvent(
        title="Spectator Count Test",
        archetype_key="small_healthcare",
        difficulty="medium",
        seed=7,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        status="live",
    )
    db.add(event)
    await db.flush()
    active_match = ArenaMatch(
        id=str(uuid.uuid4()), seed=9, archetype_key="small_healthcare", mode="pvp",
        status="active", event_id=event.id, started_at=now,
    )
    db.add(active_match)
    await db.commit()

    ws = FakeWebSocket()
    manager.register_arena_spectator(active_match.id, ws)
    try:
        resp = await client.get(f"/api/v1/arena/events/{event.id}/live-matches")
        entry = next(m for m in resp.json() if m["id"] == active_match.id)
        assert entry["spectator_count"] == 1
    finally:
        manager.unregister_arena_spectator(active_match.id, ws)


# ── 6. _notify_arena_action_result broadcasts a REDACTED event to spectators ─

async def test_notify_arena_action_result_broadcasts_redacted_event_to_spectators():
    """End-to-end through the real persistence path (_execute_arena_action,
    the same function arena_ws_handler's attacker_action branch calls)
    followed by _notify_arena_action_result (the function Phase 5 adds its
    one new call to) — confirms a registered spectator actually receives a
    'spectator_action' event, and that it carries ONLY the redacted
    diff-derived facts (hosts_newly_compromised/hosts_newly_isolated/
    match_completed/match_status/actor/sequence_number) — never the raw
    action_type, payload, or alert."""
    from app.db.session import AsyncSessionLocal
    from app.services.org_simulation import ORG_ARCHETYPES, generate_org_state
    from app.websocket.handlers import _execute_arena_action, _notify_arena_action_result

    event_id = await _make_event()
    match_id = str(uuid.uuid4())
    seed = 555111
    archetype_key = "small_healthcare"

    async with AsyncSessionLocal() as db:
        match = ArenaMatch(
            id=match_id,
            seed=seed,
            archetype_key=archetype_key,
            mode="pvp",
            attacker_user_id=None,
            defender_user_id=None,
            status="active",
            event_id=event_id,
        )
        db.add(match)
        await db.commit()

    try:
        archetype = ORG_ARCHETYPES[archetype_key]
        state0 = generate_org_state(seed, archetype)
        target_host = state0.hosts[0]

        ws = FakeWebSocket()
        manager.register_arena_spectator(match_id, ws)

        result = await _execute_arena_action(match_id, "attacker", "gain_foothold", {"host_id": target_host.id})
        assert result is not None
        await _notify_arena_action_result(match_id, "attacker", "gain_foothold", {"host_id": target_host.id}, result, match_mode="pvp")

        spectator_events = [m for m in ws.sent if m.get("type") == "spectator_action"]
        assert len(spectator_events) == 1
        event = spectator_events[0]

        assert event["actor"] == "attacker"
        assert event["sequence_number"] == 0
        assert target_host.id in event["hosts_newly_compromised"]
        assert event["hosts_newly_isolated"] == []
        assert event["match_completed"] is False
        assert event["match_status"] is None

        # Never the raw action/alert internals.
        assert "action_type" not in event
        assert "payload" not in event
        assert "alert" not in event
    finally:
        manager.unregister_arena_spectator(match_id, ws)
        await _cleanup_match(match_id)
        await _cleanup_event(event_id)
