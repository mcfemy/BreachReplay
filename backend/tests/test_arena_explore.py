"""Tests for Live Arena Mode Phase G: POST /arena/matches/{id}/explore —
the branching debrief endpoint.

Per docs/plans/live-arena-mode.md Phase G, the single most important
correctness property is that exploration is 100% read-only against
arena_matches/arena_actions for the real match: it must NEVER call
_persist_arena_action or write anything to the arena_actions table. These
tests build a real, completed multi-action match (using the exact
persistence helpers arena_ws_handler uses, mirroring test_arena.py's
existing conventions), then verify:

1. The alternate outcome genuinely diverges from real history in an
   observable way (isolating a host that was never isolated for real).
2. The real match's arena_actions row count/content is byte-identical
   before and after the explore call (queried directly via the DB
   fixture, not just through the API).
3. Calling the endpoint twice with the same alternate action produces an
   identical result (determinism holds for exploration too).
4. A non-participant is rejected (403), and a still-active (non-completed)
   match is rejected (400) — exploration is a post-game debrief feature.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.arena import ArenaMatch, ArenaAction
from app.services.org_simulation import ORG_ARCHETYPES, apply_attacker_action, apply_defender_action, _derive_rng, generate_org_state
from app.websocket.handlers import _persist_arena_action

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _build_completed_match(db, test_org, attacker_id, defender_id, seed=7777, archetype_key="small_healthcare"):
    """Build a real ArenaMatch with a persisted, multi-action history, then
    mark it completed. Mirrors test_arena.py's _make_match + the handler's
    persistence path (apply_*_action computed alongside _persist_arena_action,
    exactly like arena_ws_handler does) so the log is a realistic, replay-
    consistent history rather than hand-crafted rows."""
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=seed,
        archetype_key=archetype_key,
        mode="pvp",
        attacker_user_id=attacker_id,
        defender_user_id=defender_id,
        status="active",
    )
    db.add(match)
    await db.flush()

    archetype = ORG_ARCHETYPES[archetype_key]
    state = generate_org_state(seed, archetype)

    # Pick a credential valid on >= 2 hosts so that dump_credentials on one
    # of those hosts (the "source") harvests a credential that is ALSO valid
    # on a different host (the "target") — the actual precondition chain
    # lateral_move requires (harvested + valid_on_host_ids contains target).
    # A credential valid on only one host can never support a real
    # lateral_move in this data model, so it's explicitly excluded here.
    cred = next(c for c in state.credentials if len(c.valid_on_host_ids) >= 2)
    source_host_id, target_host_id = cred.valid_on_host_ids[0], cred.valid_on_host_ids[1]
    source_host = state.get_host(source_host_id)

    handler_actions = [
        ("attacker", "gain_foothold", {"host_id": source_host.id}),
        ("attacker", "dump_credentials", {"host_id": source_host.id}),
        ("attacker", "lateral_move", {"credential_id": cred.id, "target_host_id": target_host_id}),
    ]

    seq = 0
    for actor, action_type, payload in handler_actions:
        if actor == "attacker":
            rng = _derive_rng(match.seed, seq)
            state, _, _ = apply_attacker_action(state, {"action_type": action_type, "payload": payload, "sequence_number": seq}, rng)
        else:
            state = apply_defender_action(state, {"action_type": action_type, "payload": payload})
        await _persist_arena_action(db, match.id, actor, action_type, payload, existing_count=seq)
        seq += 1

    match.status = "attacker_won"
    await db.commit()
    await db.refresh(match)
    return match, target_host_id, source_host.id


# ── 1 & (partially) 2: divergent outcome + no writes ────────────────────────

async def test_explore_produces_genuinely_different_outcome_and_no_writes(client, db, test_user, admin_user):
    match, target_host_id, source_host_id = await _build_completed_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )

    # Snapshot the real arena_actions rows BEFORE calling explore.
    before_rows = (
        await db.execute(
            select(ArenaAction).where(ArenaAction.match_id == match.id).order_by(ArenaAction.sequence_number)
        )
    ).scalars().all()
    before_snapshot = [
        (r.id, r.match_id, r.sequence_number, r.actor, r.action_type, r.payload) for r in before_rows
    ]
    assert len(before_snapshot) == 3

    # In the REAL history, target_host_id is never isolated — the attacker's
    # lateral_move at sequence_number=2 actually succeeds. Explore an
    # alternate history where the DEFENDER isolates target_host_id at
    # sequence_number=2 instead (dropping the real lateral_move and anything
    # after it) and confirm the alternate outcome genuinely diverges: the
    # host is isolated and NOT compromised via lateral movement.
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth_headers(test_user["token"]),
        json={
            "at_sequence_number": 2,
            "alternate_action": {
                "actor": "defender",
                "action_type": "isolate_host",
                "payload": {"host_id": target_host_id},
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["match_id"] == match.id
    assert data["at_sequence_number"] == 2
    assert data["real_action_count"] == 3

    alt_host = next(h for h in data["state"]["hosts"] if h["id"] == target_host_id)
    assert alt_host["isolated"] is True
    assert alt_host["compromise_level"] == "none"  # lateral_move never happened in this branch

    # Compare against the REAL replayed state to prove genuine divergence.
    real_resp = await client.get(
        f"/api/v1/arena/matches/{match.id}",
        headers=auth_headers(test_user["token"]),
    )
    assert real_resp.status_code == 200
    real_state = real_resp.json()["state"]
    real_host = next(h for h in real_state["hosts"] if h["id"] == target_host_id)
    assert real_host["isolated"] is False
    assert real_host["compromise_level"] != "none"  # real history: lateral_move succeeded
    assert real_host != alt_host

    # ── Core correctness property: zero writes to arena_actions for the real match ──
    after_rows = (
        await db.execute(
            select(ArenaAction).where(ArenaAction.match_id == match.id).order_by(ArenaAction.sequence_number)
        )
    ).scalars().all()
    after_snapshot = [
        (r.id, r.match_id, r.sequence_number, r.actor, r.action_type, r.payload) for r in after_rows
    ]
    assert after_snapshot == before_snapshot
    assert len(after_snapshot) == 3


# ── 2. Determinism: identical explore call twice -> identical result ───────

async def test_explore_is_deterministic_across_repeated_calls(client, db, test_user, admin_user):
    match, target_host_id, _ = await _build_completed_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id, seed=31337,
    )

    body = {
        "at_sequence_number": 1,
        "alternate_action": {
            "actor": "defender",
            "action_type": "disable_credential",
            "payload": {"credential_id": "cred-1"},
        },
    }

    resp1 = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth_headers(test_user["token"]),
        json=body,
    )
    resp2 = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth_headers(test_user["token"]),
        json=body,
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()


# ── 3. Access control ────────────────────────────────────────────────────────

async def test_explore_rejects_non_participant(client, db, test_user, admin_user):
    match, target_host_id, _ = await _build_completed_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )

    # A third user, unrelated to the match, is not a participant.
    from app.models.user import User
    from app.core.security import hash_password, create_access_token

    other = User(
        email="outsider@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Outsider",
        role="analyst",
        organization_id=test_user["org"].id,
    )
    db.add(other)
    await db.flush()
    other_token = create_access_token({"sub": other.id})
    await db.commit()

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth_headers(other_token),
        json={
            "at_sequence_number": 1,
            "alternate_action": {"actor": "defender", "action_type": "acknowledge", "payload": {}},
        },
    )
    assert resp.status_code == 403


async def test_explore_rejects_non_completed_match(client, db, test_user, admin_user):
    """Exploration is a post-game debrief feature — a still-active match
    (never marked attacker_won/defender_won/abandoned) must be rejected."""
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=1,
        archetype_key="small_healthcare",
        mode="pvp",
        attacker_user_id=test_user["user"].id,
        defender_user_id=admin_user["user"].id,
        status="active",
    )
    db.add(match)
    await db.commit()

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth_headers(test_user["token"]),
        json={
            "at_sequence_number": 0,
            "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {"segment_id": "seg-1"}},
        },
    )
    assert resp.status_code == 400


async def test_explore_rejects_out_of_range_sequence_number(client, db, test_user, admin_user):
    match, _, _ = await _build_completed_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth_headers(test_user["token"]),
        json={
            "at_sequence_number": 999,
            "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {"segment_id": "seg-1"}},
        },
    )
    assert resp.status_code == 400
