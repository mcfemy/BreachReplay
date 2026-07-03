"""
INDEPENDENT VERIFICATION SCRIPT — not part of the implementer's test suite.

Written from scratch by a separate reviewer to independently re-derive the
correctness properties claimed for Phase G (`POST /arena/matches/{id}/explore`)
without trusting backend/tests/test_arena_explore.py. Uses the app's real
fixtures (db/client/test_user/admin_user) but builds its own match, its own
scenarios, and its own assertions from first principles.

Covers:
  1. Byte-identical DB snapshot of arena_actions (ALL columns) before/after
     several /explore calls with different alternate actions at different
     sequence numbers.
  2. Determinism: identical input -> identical output, called twice.
  3. Genuine, explainable divergence (isolate_host stops lateral_move cold).
  4. Access control: non-participant -> 403; non-completed match -> 400
     for both 'active' and 'lobby' statuses.
  5. Malformed/out-of-range input: negative sequence number rejected by
     pydantic validation (422), out-of-range sequence number rejected by
     the handler (400), no crash either way.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.arena import ArenaMatch, ArenaAction
from app.models.user import User
from app.core.security import create_access_token, hash_password
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    apply_attacker_action,
    apply_defender_action,
    _derive_rng,
    generate_org_state,
)
from app.websocket.handlers import _persist_arena_action

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _full_row_snapshot(db, match_id: str):
    """Snapshot EVERY column of every arena_actions row for this match,
    ordered by sequence_number, as plain tuples (no ORM identity games)."""
    rows = (
        await db.execute(
            select(ArenaAction)
            .where(ArenaAction.match_id == match_id)
            .order_by(ArenaAction.sequence_number)
        )
    ).scalars().all()
    return [
        (
            r.id,
            r.match_id,
            r.sequence_number,
            r.actor,
            r.action_type,
            r.payload,
            r.created_at,
        )
        for r in rows
    ]


async def _build_my_own_match(db, org, attacker_id, defender_id, seed=424242, archetype_key="small_healthcare"):
    """Independently construct a completed match with a real multi-step
    action history using the same low-level persistence primitives the
    live WS handler uses (this is the only supported way to write
    arena_actions rows; hand-crafting rows without running them through
    apply_*_action first would make the log internally inconsistent with
    what replay() would produce, so mirroring the real write path here is
    correct, not cheating)."""
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

    cred = next(c for c in state.credentials if len(c.valid_on_host_ids) >= 2)
    source_host_id, target_host_id = cred.valid_on_host_ids[0], cred.valid_on_host_ids[1]

    steps = [
        ("attacker", "gain_foothold", {"host_id": source_host_id}),
        ("attacker", "dump_credentials", {"host_id": source_host_id}),
        ("attacker", "lateral_move", {"credential_id": cred.id, "target_host_id": target_host_id}),
    ]

    seq = 0
    for actor, action_type, payload in steps:
        if actor == "attacker":
            rng = _derive_rng(match.seed, seq)
            state, _, _ = apply_attacker_action(
                state, {"action_type": action_type, "payload": payload, "sequence_number": seq}, rng
            )
        else:
            state = apply_defender_action(state, {"action_type": action_type, "payload": payload})
        await _persist_arena_action(db, match.id, actor, action_type, payload, existing_count=seq)
        seq += 1

    match.status = "attacker_won"
    await db.commit()
    await db.refresh(match)
    return match, source_host_id, target_host_id, cred.id


# ── 1. DB snapshot: byte-identical before/after MULTIPLE explore calls ──────

async def test_INDEPENDENT_zero_writes_across_multiple_explore_calls(client, db, test_user, admin_user):
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )

    before = await _full_row_snapshot(db, match.id)
    assert len(before) == 3, f"expected 3 persisted actions, got {len(before)}"

    # Fire several DIFFERENT /explore calls at different sequence numbers
    # with different alternate actions, interleaved with re-snapshots.
    explore_calls = [
        {
            "at_sequence_number": 0,
            "alternate_action": {"actor": "defender", "action_type": "isolate_host", "payload": {"host_id": source_host_id}},
        },
        {
            "at_sequence_number": 1,
            "alternate_action": {"actor": "defender", "action_type": "disable_credential", "payload": {"credential_id": cred_id}},
        },
        {
            "at_sequence_number": 2,
            "alternate_action": {"actor": "defender", "action_type": "isolate_host", "payload": {"host_id": target_host_id}},
        },
        {
            "at_sequence_number": 3,
            "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {"segment_id": "does-not-matter"}},
        },
    ]

    for i, body in enumerate(explore_calls):
        resp = await client.post(
            f"/api/v1/arena/matches/{match.id}/explore",
            headers=auth(test_user["token"]),
            json=body,
        )
        assert resp.status_code == 200, f"call {i} failed: {resp.status_code} {resp.text}"
        mid_snapshot = await _full_row_snapshot(db, match.id)
        assert mid_snapshot == before, f"DB mutated after explore call {i}: {body}"

    after = await _full_row_snapshot(db, match.id)
    assert after == before, "Final snapshot differs from original — explore() mutated arena_actions!"
    assert len(after) == 3

    # Also confirm arena_matches row for this match is untouched (status,
    # completed_at etc. — the match record itself should not be touched
    # by exploration either).
    match_row = (await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))).scalar_one()
    assert match_row.status == "attacker_won"


# ── 2. Determinism, called via a fresh independent scenario ─────────────────

async def test_INDEPENDENT_determinism_two_calls_identical_output(client, db, test_user, admin_user):
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id, seed=99991,
    )
    body = {
        "at_sequence_number": 1,
        "alternate_action": {"actor": "defender", "action_type": "isolate_host", "payload": {"host_id": target_host_id}},
    }
    r1 = await client.post(f"/api/v1/arena/matches/{match.id}/explore", headers=auth(test_user["token"]), json=body)
    r2 = await client.post(f"/api/v1/arena/matches/{match.id}/explore", headers=auth(test_user["token"]), json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json(), "Same input produced different output across two independent calls"


# ── 3. Genuine, mechanically-explainable divergence ─────────────────────────

async def test_INDEPENDENT_divergence_is_mechanically_real(client, db, test_user, admin_user):
    """Real history: attacker gains foothold on source, dumps creds, then
    laterally moves to target -> target ends up compromised, not isolated.
    Alternate history: defender isolates target_host at the exact sequence
    number where the real lateral_move happened -> per apply_attacker_action's
    actual mechanics (isolated hosts must be removed from the attacker's
    reachable graph), the lateral_move never gets to run in this branch, so
    target ends up isolated=True and NOT compromised. This is a deterministic,
    mechanically explainable divergence, not noise."""
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id, seed=555555,
    )

    real_resp = await client.get(f"/api/v1/arena/matches/{match.id}", headers=auth(test_user["token"]))
    assert real_resp.status_code == 200
    real_state = real_resp.json()["state"]
    real_target = next(h for h in real_state["hosts"] if h["id"] == target_host_id)
    assert real_target["isolated"] is False
    assert real_target["compromise_level"] != "none", (
        "Sanity check failed: real history's lateral_move did not compromise target host"
    )

    explore_resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={
            "at_sequence_number": 2,  # replaces the real lateral_move (seq 2)
            "alternate_action": {"actor": "defender", "action_type": "isolate_host", "payload": {"host_id": target_host_id}},
        },
    )
    assert explore_resp.status_code == 200
    alt_state = explore_resp.json()["state"]
    alt_target = next(h for h in alt_state["hosts"] if h["id"] == target_host_id)

    assert alt_target["isolated"] is True, "Alternate history should show target host isolated"
    assert alt_target["compromise_level"] == "none", (
        "Alternate history should show target host NEVER compromised because lateral_move "
        "was replaced by isolation before it could run"
    )
    # Explicit contrast for the report.
    assert real_target["isolated"] != alt_target["isolated"]
    assert real_target["compromise_level"] != alt_target["compromise_level"]


# ── 4. Access control ────────────────────────────────────────────────────────

async def test_INDEPENDENT_non_participant_rejected(client, db, test_user, admin_user):
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )
    outsider = User(
        email="totally-uninvolved@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Uninvolved Party",
        role="analyst",
        organization_id=test_user["org"].id,
    )
    db.add(outsider)
    await db.flush()
    outsider_token = create_access_token({"sub": outsider.id})
    await db.commit()

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(outsider_token),
        json={"at_sequence_number": 0, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("status_value", ["active", "lobby"])
async def test_INDEPENDENT_non_completed_match_rejected_for_all_incomplete_statuses(client, db, test_user, admin_user, status_value):
    """Plan rationale: exploration is a post-game debrief feature meant to
    prevent mid-match meta-gaming. Confirm BOTH 'active' and 'lobby' —
    not just one arbitrarily-chosen incomplete status — are rejected."""
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=1,
        archetype_key="small_healthcare",
        mode="pvp",
        attacker_user_id=test_user["user"].id,
        defender_user_id=admin_user["user"].id,
        status=status_value,
    )
    db.add(match)
    await db.commit()

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": 0, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp.status_code == 400, f"status={status_value}: expected 400, got {resp.status_code}: {resp.text}"


# ── 5. Malformed / out-of-range input ────────────────────────────────────────

async def test_INDEPENDENT_out_of_range_sequence_number_rejected_cleanly(client, db, test_user, admin_user):
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )
    # Real match has exactly 3 actions (sequence_numbers 0,1,2) -> valid
    # at_sequence_number range is [0, 3]. 3 itself means "append after the
    # full real log" and should be VALID; 4+ should be rejected.
    resp_too_far = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": 4, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp_too_far.status_code == 400, f"expected 400, got {resp_too_far.status_code}: {resp_too_far.text}"

    resp_way_too_far = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": 999999, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp_way_too_far.status_code == 400

    # Boundary: exactly len(real_actions) should be accepted (append at end).
    resp_exact_boundary = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": 3, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp_exact_boundary.status_code == 200, f"boundary case failed: {resp_exact_boundary.text}"


async def test_INDEPENDENT_negative_sequence_number_rejected_cleanly(client, db, test_user, admin_user):
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": -1, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    # Pydantic field_validator raises ValueError -> FastAPI turns this into
    # a 422 Unprocessable Entity (request validation failure), not a 500.
    assert resp.status_code == 422, f"expected 422 for negative sequence number, got {resp.status_code}: {resp.text}"


async def test_INDEPENDENT_malformed_actor_rejected_cleanly(client, db, test_user, admin_user):
    match, source_host_id, target_host_id, cred_id = await _build_my_own_match(
        db, test_user["org"], test_user["user"].id, admin_user["user"].id,
    )
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": 0, "alternate_action": {"actor": "referee", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp.status_code == 422, f"expected 422 for invalid actor, got {resp.status_code}: {resp.text}"


async def test_INDEPENDENT_nonexistent_match_returns_404(client, db, test_user):
    resp = await client.post(
        f"/api/v1/arena/matches/{uuid.uuid4()}/explore",
        headers=auth(test_user["token"]),
        json={"at_sequence_number": 0, "alternate_action": {"actor": "attacker", "action_type": "discover_segment", "payload": {}}},
    )
    assert resp.status_code == 404
