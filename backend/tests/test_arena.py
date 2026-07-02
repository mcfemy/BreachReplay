"""Tests for Live Arena Mode Phase C: REST match orchestration endpoints
plus the WS-handler-internal helpers/invariants from
app/websocket/handlers.py's arena_ws_handler.

WS-transport-level testing (starlette TestClient.websocket_connect) was
evaluated and found genuinely incompatible with this codebase's existing
test fixtures: the per-IP WS rate limiter (app/main.py's
_ws_rate_allowed) talks to a fakeredis instance bound to pytest-asyncio's
event loop (see conftest.py's `setup_redis` fixture), while
TestClient.websocket_connect runs the ASGI app on Starlette's own
synchronous portal thread with a DIFFERENT event loop — the fakeredis
client raises "bound to a different event loop" as soon as the WS route's
rate-limit check runs. Rather than rework the global rate-limiter/fixture
architecture (out of scope for this phase), these tests exercise the
handler's internals directly (the same functions arena_ws_handler calls:
_load_match_and_actions, _persist_arena_action, _decision_gate_trigger,
apply_attacker_action/apply_defender_action/replay) plus the REST layer,
per the plan's explicit "integration test calling the REST+persistence
layer directly if WS testing isn't already set up here" allowance.
"""
import asyncio
import uuid

import pytest

from app.models.arena import ArenaMatch, ArenaAction
from app.services.org_simulation import ORG_ARCHETYPES, replay
from app.websocket.handlers import (
    _load_match_and_actions,
    _persist_arena_action,
    _decision_gate_trigger,
    _role_for_user,
)
from app.websocket.manager import manager

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 1. REST: match creation ─────────────────────────────────────────────────

async def test_create_match_human_attacks_vs_ai(client, test_user):
    resp = await client.post(
        "/api/v1/arena/matches",
        headers=auth_headers(test_user["token"]),
        json={"mode": "human_attacks_vs_ai", "archetype_key": "small_healthcare"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "human_attacks_vs_ai"
    assert data["status"] == "lobby"
    assert data["attacker_user_id"] == test_user["user"].id
    assert data["defender_user_id"] is None
    # Attacker's initial view must NOT leak host-level detail (unpatched
    # CVEs, credentials, etc.) — only coarse segment shape.
    assert "segment_count" in data["attacker_view"]
    assert "hosts" not in data["attacker_view"]
    # Defender's initial view has hosts but no unpatched_cves field leaked.
    assert "hosts" in data["defender_view"]
    for h in data["defender_view"]["hosts"]:
        assert "unpatched_cves" not in h


async def test_create_match_human_defends_vs_ai(client, test_user):
    resp = await client.post(
        "/api/v1/arena/matches",
        headers=auth_headers(test_user["token"]),
        json={"mode": "human_defends_vs_ai", "archetype_key": "energy_utility"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["defender_user_id"] == test_user["user"].id
    assert data["attacker_user_id"] is None


async def test_create_match_unknown_archetype_rejected(client, test_user):
    resp = await client.post(
        "/api/v1/arena/matches",
        headers=auth_headers(test_user["token"]),
        json={"mode": "human_attacks_vs_ai", "archetype_key": "not_a_real_archetype"},
    )
    assert resp.status_code == 400


async def test_create_match_pvp_requires_current_user_participation(client, test_user):
    resp = await client.post(
        "/api/v1/arena/matches",
        headers=auth_headers(test_user["token"]),
        json={
            "mode": "pvp",
            "archetype_key": "small_healthcare",
            "attacker_user_id": "someone-else",
            "defender_user_id": "someone-else-2",
        },
    )
    assert resp.status_code == 400


async def test_get_match_requires_participant(client, test_user, admin_user):
    create_resp = await client.post(
        "/api/v1/arena/matches",
        headers=auth_headers(test_user["token"]),
        json={"mode": "human_attacks_vs_ai", "archetype_key": "small_healthcare"},
    )
    match_id = create_resp.json()["id"]

    forbidden = await client.get(
        f"/api/v1/arena/matches/{match_id}",
        headers=auth_headers(admin_user["token"]),
    )
    assert forbidden.status_code == 403

    ok = await client.get(
        f"/api/v1/arena/matches/{match_id}",
        headers=auth_headers(test_user["token"]),
    )
    assert ok.status_code == 200
    assert ok.json()["action_count"] == 0
    assert ok.json()["state"]["hosts"]


async def test_list_my_matches(client, test_user):
    for _ in range(2):
        await client.post(
            "/api/v1/arena/matches",
            headers=auth_headers(test_user["token"]),
            json={"mode": "human_attacks_vs_ai", "archetype_key": "small_healthcare"},
        )
    resp = await client.get("/api/v1/arena/matches", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


# ── helpers for the handler-internals tests below ───────────────────────────

async def _make_match(db, test_org, attacker_id="attacker-1", defender_id="defender-1", archetype_key="small_healthcare", seed=4242):
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
    return match


# ── 2. Two-sided playtest: containment measurably blocks a later attacker move ──

async def test_defender_containment_blocks_subsequent_attacker_action(db, test_org):
    """Mirrors the plan's Phase C verification requirement: an attacker
    move, followed by a defender containment action, measurably and
    correctly changes what the attacker's NEXT action can do — using the
    exact functions arena_ws_handler calls (apply_attacker_action /
    apply_defender_action), fed by _load_match_and_actions /
    _persist_arena_action the same way the WS handler does."""
    match = await _make_match(db, test_org)
    await db.commit()

    from app.services.org_simulation import generate_org_state, apply_attacker_action, apply_defender_action, _derive_rng

    archetype = ORG_ARCHETYPES[match.archetype_key]
    state0 = generate_org_state(match.seed, archetype)

    # Find a credential/host pair that will let us demonstrate lateral_move.
    cred = next(c for c in state0.credentials if c.valid_on_host_ids)
    target_host_id = cred.valid_on_host_ids[0]
    source_host = next(h for h in state0.hosts if h.id != target_host_id)

    # Sequence 0: attacker gains foothold on source_host.
    _, action_dicts = await _load_match_and_actions(db, match.id)
    assert action_dicts == []
    rng0 = _derive_rng(match.seed, 0)
    state1, _, _ = apply_attacker_action(state0, {"action_type": "gain_foothold", "payload": {"host_id": source_host.id}, "sequence_number": 0}, rng0)
    await _persist_arena_action(db, match.id, "attacker", "gain_foothold", {"host_id": source_host.id}, existing_count=0)

    # Sequence 1: attacker dumps credentials on source_host.
    _, action_dicts = await _load_match_and_actions(db, match.id)
    assert len(action_dicts) == 1
    rng1 = _derive_rng(match.seed, 1)
    state2, _, _ = apply_attacker_action(state1, {"action_type": "dump_credentials", "payload": {"host_id": source_host.id}, "sequence_number": 1}, rng1)
    await _persist_arena_action(db, match.id, "attacker", "dump_credentials", {"host_id": source_host.id}, existing_count=1)

    # Sequence 2: DEFENDER isolates the target host BEFORE the attacker can reach it.
    state3 = apply_defender_action(state2, {"action_type": "isolate_host", "payload": {"host_id": target_host_id}})
    await _persist_arena_action(db, match.id, "defender", "isolate_host", {"host_id": target_host_id}, existing_count=2)
    assert state3.get_host(target_host_id).isolated is True

    # Sequence 3: attacker's lateral_move against the now-isolated host must fail
    # (measurably blocked), even though the credential is harvested/valid.
    _, action_dicts = await _load_match_and_actions(db, match.id)
    assert len(action_dicts) == 3
    rng3 = _derive_rng(match.seed, 3)
    state4, detected, alert = apply_attacker_action(
        state3,
        {"action_type": "lateral_move", "payload": {"credential_id": cred.id, "target_host_id": target_host_id}, "sequence_number": 3},
        rng3,
    )
    assert state4.get_host(target_host_id).compromise_level == "none"
    assert state4.to_dict() == state3.to_dict()  # no-op: containment worked
    await db.commit()


# ── 3. Critical invariant: replay() reconstructs EXACTLY what the handler computed ──

async def test_replay_reconstructs_exact_handler_state(db, test_org):
    """The single most important test in this phase: after a sequence of
    attacker+defender actions persisted via the same helper functions
    arena_ws_handler uses, org_simulation.replay() over the persisted log
    must reconstruct EXACTLY the state the handler computed incrementally,
    action by action."""
    match = await _make_match(db, test_org, seed=999)
    await db.commit()

    from app.services.org_simulation import generate_org_state, apply_attacker_action, apply_defender_action, _derive_rng

    archetype = ORG_ARCHETYPES[match.archetype_key]
    state = generate_org_state(match.seed, archetype)

    host_a = state.hosts[0]
    host_b = state.hosts[1] if len(state.hosts) > 1 else state.hosts[0]
    segment_a = state.segments[0]

    handler_actions = [
        ("attacker", "discover_segment", {"segment_id": segment_a.id}),
        ("attacker", "gain_foothold", {"host_id": host_a.id}),
        ("attacker", "dump_credentials", {"host_id": host_a.id}),
        ("defender", "increase_monitoring", {"segment_id": segment_a.id}),
        ("attacker", "escalate_privilege", {"host_id": host_a.id}),
        ("defender", "isolate_host", {"host_id": host_b.id}),
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

    handler_final_state_dict = state.to_dict()

    # Now reconstruct via the SAME path GET /arena/matches/{id} uses.
    _, action_dicts = await _load_match_and_actions(db, match.id)
    assert len(action_dicts) == len(handler_actions)
    replayed_state, events = replay(match.seed, match.archetype_key, action_dicts)

    assert replayed_state.to_dict() == handler_final_state_dict
    assert len(events) == len(handler_actions)
    await db.commit()


# ── 4. Concurrency: two simultaneous attacker_action messages get distinct, ordered sequence_numbers ──

async def test_concurrent_actions_get_distinct_ordered_sequence_numbers(db, test_org):
    """Fires two 'attacker_action'-equivalent persistence flows for the SAME
    match at effectively the same time (asyncio.gather) and confirms the
    per-match asyncio.Lock (manager.get_arena_match_lock) — the mechanism
    arena_ws_handler actually uses — prevents both from computing/persisting
    the same sequence_number. Without the lock, both concurrent tasks would
    read existing_count=0 and attempt to insert sequence_number=0 twice,
    which the model's UniqueConstraint would also catch, but the lock is
    meant to prevent the race outright rather than rely on the DB to reject
    the loser."""
    match = await _make_match(db, test_org, seed=13)
    await db.commit()

    match_id = match.id
    lock = manager.get_arena_match_lock(match_id)

    results = []

    async def do_one_action(action_type: str, payload: dict):
        async with lock:
            _, action_dicts = await _load_match_and_actions(db, match_id)
            existing_count = len(action_dicts)
            # Simulate handler work happening between the count-read and the
            # insert (replay + apply_attacker_action) — if the lock weren't
            # held for this whole critical section, this sleep would let the
            # other coroutine interleave and observe the same existing_count.
            await asyncio.sleep(0.01)
            action = await _persist_arena_action(db, match_id, "attacker", action_type, payload, existing_count=existing_count)
            results.append(action.sequence_number)

    await asyncio.gather(
        do_one_action("discover_segment", {"segment_id": "seg-1"}),
        do_one_action("discover_host", {"host_id": "host-1"}),
    )

    assert sorted(results) == [0, 1]  # distinct, no lost/duplicated sequence_numbers

    _, action_dicts = await _load_match_and_actions(db, match_id)
    assert len(action_dicts) == 2
    seq_numbers = sorted(a["sequence_number"] for a in action_dicts)
    assert seq_numbers == [0, 1]


async def test_role_for_user():
    match = ArenaMatch(id="m1", seed=1, archetype_key="small_healthcare", mode="pvp",
                        attacker_user_id="u-att", defender_user_id="u-def", status="active")
    assert _role_for_user(match, "u-att") == "attacker"
    assert _role_for_user(match, "u-def") == "defender"
    assert _role_for_user(match, "u-nobody") is None


# ── 5. Decision gate trigger logic ──────────────────────────────────────────

async def test_decision_gate_trigger_fires_on_admin_compromise():
    from app.services.org_simulation import generate_org_state, apply_attacker_action, _derive_rng

    state = generate_org_state(555, ORG_ARCHETYPES["small_healthcare"])
    host = next(h for h in state.hosts if h.unpatched_cves)
    state1, _, _ = apply_attacker_action(state, {"action_type": "gain_foothold", "payload": {"host_id": host.id}}, _derive_rng(555, 0))
    state2, _, _ = apply_attacker_action(state1, {"action_type": "escalate_privilege", "payload": {"host_id": host.id}}, _derive_rng(555, 1))

    trigger = _decision_gate_trigger("escalate_privilege", {"host_id": host.id}, state1, state2)
    assert trigger is not None
    reason, host_dict, credential_id = trigger
    assert host_dict["id"] == host.id


async def test_decision_gate_trigger_fires_on_deploy_impact():
    from app.services.org_simulation import Host, NetworkSegment, OrgState

    segments = (NetworkSegment(id="seg-1", name="corp"),)
    hosts = (Host(id="host-a", hostname="A", role="workstation", network_segment_id="seg-1", compromise_level="admin"),)
    state = OrgState(hosts=hosts, segments=segments)
    trigger = _decision_gate_trigger("deploy_impact", {"host_id": "host-a"}, state, state)
    assert trigger is not None
    assert trigger[1]["id"] == "host-a"


async def test_decision_gate_trigger_none_for_recon_actions():
    from app.services.org_simulation import generate_org_state
    state = generate_org_state(1, ORG_ARCHETYPES["small_healthcare"])
    assert _decision_gate_trigger("discover_segment", {"segment_id": "seg-1"}, state, state) is None


# ── 6. Decision gate option payloads are always actionable ─────────────────
# Regression coverage for a real bug found in review: options were being
# stamped with host_id/credential_id regardless of which ID each
# response_action_type actually needs, so clicking "increase monitoring"
# (needs segment_id, never supplied) or "disable credential" (credential_id
# frequently None) would silently no-op on the defender side.

async def test_decision_gate_options_only_offer_actionable_response_types():
    from app.websocket.handlers import _build_arena_decision_gate

    host = {"id": "h1", "hostname": "DC01", "role": "domain_controller", "network_segment_id": "seg-corp"}

    # No credential known (e.g. a deploy_impact trigger) — disable_credential
    # must not be offered, since clicking it would no-op with credential_id=None.
    gate = _build_arena_decision_gate("Impact activity in progress", host, None, 5)
    offered = {o["response_action_type"] for o in gate["options"]}
    assert "disable_credential" not in offered
    assert "increase_monitoring" in offered
    mon_opt = next(o for o in gate["options"] if o["response_action_type"] == "increase_monitoring")
    assert mon_opt["segment_id"] == "seg-corp"
    assert "credential_id" not in mon_opt and "host_id" not in mon_opt

    # Credential known — disable_credential is offered with the real ID, and
    # each option only carries the field(s) it actually needs.
    gate2 = _build_arena_decision_gate("Host reached admin-level compromise", host, "cred-42", 6)
    disable_opt = next(o for o in gate2["options"] if o["response_action_type"] == "disable_credential")
    assert disable_opt["credential_id"] == "cred-42"
    assert "host_id" not in disable_opt
    isolate_opt = next(o for o in gate2["options"] if o["response_action_type"] == "isolate_host")
    assert isolate_opt["host_id"] == "h1"
    assert "credential_id" not in isolate_opt

    # No host at all — only the payload-less acknowledge option survives.
    gate3 = _build_arena_decision_gate("Unclear activity detected", None, None, 7)
    assert {o["response_action_type"] for o in gate3["options"]} == {"acknowledge"}
