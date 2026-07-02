"""Independent verification tests for Phase C — Live Arena Mode orchestration.

Written by an independent reviewer, NOT the implementer, specifically to
avoid trusting the implementer's own test_arena.py. Exercises:

1. A longer (7-action), mixed attacker/defender sequence different from the
   implementer's 6-action test (different archetype, different action mix,
   different hosts/segments/credentials touched) to independently confirm
   replay() reconstructs exactly what incremental application produced.
2. A 5-way (not 2-way) concurrent action race on the SAME match, confirming
   the per-match asyncio.Lock yields exactly 5 distinct, gapless,
   0..4 sequence_numbers with no duplicates and no gaps.
"""
import asyncio
import uuid

import pytest

from app.models.arena import ArenaMatch
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    generate_org_state,
    apply_attacker_action,
    apply_defender_action,
    replay,
    _derive_rng,
)
from app.websocket.handlers import _load_match_and_actions, _persist_arena_action
from app.websocket.manager import manager

pytestmark = pytest.mark.asyncio


async def _make_match(db, archetype_key, seed, attacker_id="atk-indep", defender_id="def-indep"):
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


async def test_independent_mixed_7_action_replay_matches_incremental(db, test_org):
    """Independent variant of test_replay_reconstructs_exact_handler_state:
    different archetype (energy_utility, not small_healthcare), different
    seed, 7 actions (not 6), and a different action-type mix (includes
    patch_host and discover_host, which the implementer's test did not
    exercise), touching 3 distinct hosts instead of 2."""
    match = await _make_match(db, "energy_utility", seed=77001)
    await db.commit()

    archetype = ORG_ARCHETYPES[match.archetype_key]
    state = generate_org_state(match.seed, archetype)

    assert len(state.hosts) >= 3, "need at least 3 hosts for this scenario"
    host_a, host_b, host_c = state.hosts[0], state.hosts[1], state.hosts[2]
    segment_a = state.segments[0]

    # Deliberately different action mix/order from the implementer's test.
    handler_actions = [
        ("attacker", "discover_host", {"host_id": host_a.id}),
        ("attacker", "gain_foothold", {"host_id": host_a.id}),
        ("defender", "patch_host", {"host_id": host_b.id}),
        ("attacker", "dump_credentials", {"host_id": host_a.id}),
        ("defender", "increase_monitoring", {"segment_id": segment_a.id}),
        ("attacker", "escalate_privilege", {"host_id": host_a.id}),
        ("defender", "isolate_host", {"host_id": host_c.id}),
    ]

    seq = 0
    for actor, action_type, payload in handler_actions:
        if actor == "attacker":
            rng = _derive_rng(match.seed, seq)
            state, _, _ = apply_attacker_action(
                state, {"action_type": action_type, "payload": payload, "sequence_number": seq}, rng
            )
        else:
            state = apply_defender_action(state, {"action_type": action_type, "payload": payload})
        await _persist_arena_action(db, match.id, actor, action_type, payload, existing_count=seq)
        seq += 1

    incremental_final_dict = state.to_dict()

    _, action_dicts = await _load_match_and_actions(db, match.id)
    assert len(action_dicts) == 7

    replayed_state, events = replay(match.seed, match.archetype_key, action_dicts)

    assert replayed_state.to_dict() == incremental_final_dict, (
        "replay() diverged from incremental handler-equivalent application "
        "over a 7-action mixed sequence"
    )
    assert len(events) == 7

    # Additionally confirm replay() is idempotent/deterministic when called
    # a second time over the identical persisted log (byte-identical output).
    replayed_state_2, events_2 = replay(match.seed, match.archetype_key, action_dicts)
    assert replayed_state_2.to_dict() == replayed_state.to_dict()
    assert events_2 == events

    await db.commit()


async def test_independent_five_concurrent_actions_get_gapless_sequence_numbers(db, test_org):
    """Independent variant of test_concurrent_actions_get_distinct_ordered_
    sequence_numbers: fires 5 (not 2) concurrent action-persistence flows
    against the SAME match via asyncio.gather, using the actual
    manager.get_arena_match_lock(match_id) mechanism arena_ws_handler uses.
    Confirms the result is exactly {0, 1, 2, 3, 4} — no gaps, no duplicates,
    no lost updates — under 5-way contention rather than 2-way."""
    match = await _make_match(db, "small_healthcare", seed=55501)
    await db.commit()

    match_id = match.id
    lock = manager.get_arena_match_lock(match_id)

    results = []

    async def do_one_action(tag: str):
        async with lock:
            _, action_dicts = await _load_match_and_actions(db, match_id)
            existing_count = len(action_dicts)
            # Force interleaving opportunity: if the lock did NOT cover this
            # entire critical section, all 5 coroutines would race to read
            # existing_count=0 during this sleep window.
            await asyncio.sleep(0.01)
            action = await _persist_arena_action(
                db, match_id, "attacker", "discover_host", {"host_id": f"host-{tag}"},
                existing_count=existing_count,
            )
            results.append(action.sequence_number)

    await asyncio.gather(*(do_one_action(str(i)) for i in range(5)))

    assert sorted(results) == [0, 1, 2, 3, 4], f"expected gapless 0..4, got {sorted(results)}"
    assert len(set(results)) == 5, "duplicate sequence_number assigned under concurrency"

    _, action_dicts = await _load_match_and_actions(db, match_id)
    assert len(action_dicts) == 5
    seq_numbers = sorted(a["sequence_number"] for a in action_dicts)
    assert seq_numbers == [0, 1, 2, 3, 4]

    await db.commit()
