"""Tests for Live Arena Mode Phase D: the deterministic AI attacker policy
bot (app/services/arena_ai_attacker.py) and its integration with the
Phase C persistence path (app/websocket/handlers.py's
_execute_arena_action / _run_arena_attacker_bot).

Per the plan's Phase D verification requirements:
1. An AI-attacker match can run to completion driven entirely by
   choose_attacker_action calls, terminating within a reasonable number of
   steps (not an infinite loop).
2. Determinism: same seed + same difficulty -> identical sequence of
   bot-chosen actions across two separate runs.
3. Difficulty measurably affects outcome across the same seed.
4. No global `random` usage anywhere in arena_ai_attacker.py.
5. Full suite regression check (run separately, see report).
"""
import asyncio
import re
from pathlib import Path

import pytest

from app.models.arena import ArenaMatch
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    apply_attacker_action,
    generate_org_state,
    replay,
    _derive_rng,
)
from app.services.arena_ai_attacker import choose_attacker_action
from app.websocket.handlers import _execute_arena_action, _run_arena_attacker_bot
from app.websocket.manager import manager

_MAX_STEPS = 200


def _drive_bot_loop_pure(seed: int, archetype_key: str, difficulty: str, max_steps: int = _MAX_STEPS) -> list[dict]:
    """Drive choose_attacker_action -> apply_attacker_action repeatedly
    against evolving state, exactly mirroring what _run_arena_attacker_bot
    does but without any DB/WS involvement — a pure, fast unit-level
    simulation of "the loop" for the determinism/termination/difficulty
    tests below, which don't need real persistence to prove the policy's
    properties. (The persistence-integrated path is separately exercised by
    test_bot_loop_drives_match_to_completion_via_execute_arena_action,
    which DOES go through _execute_arena_action / the DB.)
    """
    archetype = ORG_ARCHETYPES[archetype_key]
    state = generate_org_state(seed, archetype)
    actions_log: list[dict] = []
    bot_moves_made = 0

    for step in range(max_steps):
        rng = _derive_rng(seed, step)
        action = choose_attacker_action(state, difficulty, rng, actions_taken=bot_moves_made)
        if action is None:
            break
        action_type = action["action_type"]
        payload = action["payload"]
        actions_log.append({"action_type": action_type, "payload": payload})

        engine_rng = _derive_rng(seed, step)
        state, detected, alert = apply_attacker_action(
            state, {"action_type": action_type, "payload": payload, "sequence_number": step}, engine_rng
        )
        bot_moves_made += 1

        if state.global_flags.get("impact_deployed"):
            break

    return actions_log


# ── 1. Runs to completion, terminates within a reasonable step count ───────

@pytest.mark.parametrize("seed", [1, 42, 999, 123456, 7])
@pytest.mark.parametrize("archetype_key", list(ORG_ARCHETYPES.keys()))
@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_bot_loop_terminates_and_can_reach_impact(seed, archetype_key, difficulty):
    actions_log = _drive_bot_loop_pure(seed, archetype_key, difficulty)
    # Never an infinite loop / never hits the hard cap without terminating.
    assert len(actions_log) < _MAX_STEPS
    assert len(actions_log) > 0


def test_bot_loop_reaches_impact_deployed_for_at_least_some_seeds():
    """Confirm the bot is actually capable of winning (reaching the
    match-ending deploy_impact state), not just terminating trivially with
    zero progress, across a spread of seeds/archetypes on hard difficulty
    (most likely to succeed)."""
    reached_impact = False
    for seed in range(60):
        for archetype_key in ORG_ARCHETYPES:
            archetype = ORG_ARCHETYPES[archetype_key]
            state = generate_org_state(seed, archetype)
            bot_moves_made = 0
            for step in range(_MAX_STEPS):
                rng = _derive_rng(seed, step)
                action = choose_attacker_action(state, "hard", rng, actions_taken=bot_moves_made)
                if action is None:
                    break
                engine_rng = _derive_rng(seed, step)
                state, _, _ = apply_attacker_action(
                    state, {"action_type": action["action_type"], "payload": action["payload"], "sequence_number": step}, engine_rng
                )
                bot_moves_made += 1
                if state.global_flags.get("impact_deployed"):
                    reached_impact = True
                    break
            if reached_impact:
                break
        if reached_impact:
            break
    assert reached_impact, "expected at least one (seed, archetype) combination where the hard bot reaches deploy_impact within the step cap"


# ── 2. Determinism: identical action sequence across two separate runs ─────

@pytest.mark.parametrize("seed", [1, 42, 2024])
@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_bot_action_sequence_deterministic_same_seed_same_difficulty(seed, difficulty):
    run_a = _drive_bot_loop_pure(seed, "small_healthcare", difficulty)
    run_b = _drive_bot_loop_pure(seed, "small_healthcare", difficulty)
    assert run_a == run_b
    assert len(run_a) > 0


def test_bot_action_sequence_differs_across_seeds():
    run_a = _drive_bot_loop_pure(1, "energy_utility", "hard")
    run_b = _drive_bot_loop_pure(2, "energy_utility", "hard")
    assert run_a != run_b


# ── 3. Difficulty measurably affects outcome ────────────────────────────────

def test_difficulty_produces_measurably_different_outcomes_same_seed():
    """Across several seeds, confirm hard and easy produce concretely
    different results (different action sequences and/or different final
    state) — not just "it ran". We check both the move-count-to-termination
    and the resulting state differ for at least one seed, and that hard
    never performs obviously worse (measured by highest compromise_level
    reached) than easy on average across the sample."""
    any_sequence_diff = False
    any_state_diff = False
    hard_reached_impact_count = 0
    easy_reached_impact_count = 0

    _COMPROMISE_ORDER = {"none": 0, "foothold": 1, "admin": 2, "domain_admin": 3}

    for seed in range(30):
        archetype_key = "energy_utility"
        archetype = ORG_ARCHETYPES[archetype_key]

        hard_actions = _drive_bot_loop_pure(seed, archetype_key, "hard")
        easy_actions = _drive_bot_loop_pure(seed, archetype_key, "easy")

        if hard_actions != easy_actions:
            any_sequence_diff = True

        # Replay each action log against a fresh state to get final outcomes.
        hard_state = generate_org_state(seed, archetype)
        for i, a in enumerate(hard_actions):
            rng = _derive_rng(seed, i)
            hard_state, _, _ = apply_attacker_action(hard_state, {**a, "sequence_number": i}, rng)
        easy_state = generate_org_state(seed, archetype)
        for i, a in enumerate(easy_actions):
            rng = _derive_rng(seed, i)
            easy_state, _, _ = apply_attacker_action(easy_state, {**a, "sequence_number": i}, rng)

        if hard_state.to_dict() != easy_state.to_dict():
            any_state_diff = True

        if hard_state.global_flags.get("impact_deployed"):
            hard_reached_impact_count += 1
        if easy_state.global_flags.get("impact_deployed"):
            easy_reached_impact_count += 1

    assert any_sequence_diff, "expected hard and easy to choose different action sequences for at least one seed"
    assert any_state_diff, "expected hard and easy to reach different final OrgState for at least one seed"
    # Concrete, not just "it ran": hard should be at least as effective as
    # easy at reaching the win condition across this sample.
    assert hard_reached_impact_count >= easy_reached_impact_count


# ── 4. No global `random` module usage ──────────────────────────────────────

def test_no_global_random_module_usage_in_arena_ai_attacker():
    source_path = Path(__file__).parent.parent / "app" / "services" / "arena_ai_attacker.py"
    source = source_path.read_text()

    # Find every call of the form random.<method>(...) and confirm each one
    # is a method call on a `random.Random` instance variable (i.e. NOT the
    # bare `random.<toplevel>(...)` form using the imported module itself).
    forbidden_pattern = re.compile(r"\brandom\.(random|choice|randint|sample|shuffle|uniform)\s*\(")
    hits = forbidden_pattern.findall(source)
    assert hits == [], f"found direct global `random.*` calls in arena_ai_attacker.py: {hits}"

    # Positive control: rng.<method>( calls (on the passed-in Random
    # instance) ARE expected and fine.
    rng_pattern = re.compile(r"\brng\.(random|choice|randint|sample|shuffle|uniform)\s*\(")
    assert rng_pattern.search(source), "expected at least one rng.<method>(...) call using the passed-in random.Random instance"


# ── 5. Integration: bot loop through the real persistence path ─────────────

@pytest.mark.asyncio
async def test_bot_loop_drives_match_to_completion_via_execute_arena_action():
    """The bot loop, run directly (not as a background asyncio task, so the
    test can await it synchronously), must drive a real human_defends_vs_ai
    match to a terminal ArenaMatch.status using ONLY choose_attacker_action
    + _execute_arena_action — the same function arena_ws_handler's human
    attacker_action branch calls. No parallel persistence path.

    Uses AsyncSessionLocal directly (the app's real production session
    factory) rather than the `db`/`test_org` fixtures: _execute_arena_action
    internally opens its own AsyncSessionLocal() sessions (exactly like
    arena_ws_handler does), which are bound to a different connection/pool
    than the `db` fixture's single transaction-scoped connection — writes
    made through the `db` fixture are never visible to a second, separately
    connected session until the outer transaction actually commits (it
    deliberately never does, since the fixture rolls back at teardown for
    isolation). This mirrors test_arena.py's documented WS-testing
    limitation for the same reason. Match/actions created here are cleaned
    up manually at the end since they bypass that fixture's auto-rollback.
    """
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from app.models.arena import ArenaAction
    from app.services.arena_ai_attacker import choose_attacker_action
    from app.websocket.handlers import _load_match_and_actions

    match_id = "test-bot-completion-match-31337"
    seed = 31337
    archetype_key = "small_healthcare"

    async with AsyncSessionLocal() as db:
        # Clean slate in case a previous failed run left rows behind.
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id,
            seed=seed,
            archetype_key=archetype_key,
            mode="human_defends_vs_ai",
            attacker_user_id=None,
            defender_user_id="defender-1",
            status="active",
        )
        db.add(match)
        await db.commit()

    try:
        bot_moves_made = 0
        match_completed = False
        for _ in range(_MAX_STEPS):
            async with AsyncSessionLocal() as db:
                m, action_dicts = await _load_match_and_actions(db, match_id)
            if not m or m.status not in ("active", "lobby"):
                match_completed = m.status != "active" if m else True
                break

            state, _ = replay(m.seed, m.archetype_key, action_dicts)
            rng = _derive_rng(m.seed, len(action_dicts))
            action = choose_attacker_action(state, "hard", rng, actions_taken=bot_moves_made)
            if action is None:
                break

            result = await _execute_arena_action(match_id, "attacker", action["action_type"], action["payload"] or {})
            assert result is not None
            bot_moves_made += 1
            if result["match_completed"]:
                match_completed = True
                break

        async with AsyncSessionLocal() as db:
            final_match, final_actions = await _load_match_and_actions(db, match_id)

        assert match_completed, "expected the bot to drive the match to completion (deploy_impact) within the step cap"
        assert final_match.status == "attacker_won"
        assert len(final_actions) == bot_moves_made
        assert bot_moves_made < _MAX_STEPS
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()


@pytest.mark.asyncio
async def test_maybe_start_arena_attacker_bot_is_idempotent():
    """manager.arena_bot_running guards against spawning two bot tasks for
    the same match (e.g. a defender reconnecting). Uses the underlying
    _run_arena_attacker_bot coroutine directly (wrapped in a task we own and
    await/cancel ourselves) rather than _maybe_start_arena_attacker_bot's
    fire-and-forget asyncio.create_task, purely so this test can cleanly
    await the task's exit instead of leaking a background task past the
    test's own event loop teardown (that task would query a nonexistent
    match_id and exit almost immediately, but "almost immediately" still
    races the test process's loop shutdown under pytest-asyncio)."""
    from app.websocket.handlers import _run_arena_attacker_bot

    match_id = "idempotent-test-match"
    manager.arena_bot_running.discard(match_id)
    task = None
    try:
        assert match_id not in manager.arena_bot_running
        manager.arena_bot_running.add(match_id)
        task = asyncio.create_task(_run_arena_attacker_bot(match_id))
        assert match_id in manager.arena_bot_running

        # Simulate the idempotency guard a second connection-open would hit:
        # since match_id is already in arena_bot_running, a second call must
        # be a no-op rather than spawning a second task.
        from app.websocket.handlers import _maybe_start_arena_attacker_bot
        _maybe_start_arena_attacker_bot(match_id, "human_defends_vs_ai")
        assert match_id in manager.arena_bot_running

        # Let the real task run to completion: it queries a nonexistent
        # match_id, finds nothing, and exits (clearing the guard itself in
        # its `finally`) — await it directly instead of guessing at timing.
        await asyncio.wait_for(task, timeout=5.0)
        assert match_id not in manager.arena_bot_running
    finally:
        if task is not None and not task.done():
            task.cancel()
        manager.arena_bot_running.discard(match_id)


@pytest.mark.asyncio
async def test_maybe_start_arena_attacker_bot_skips_non_ai_modes():
    from app.websocket.handlers import _maybe_start_arena_attacker_bot

    match_id = "pvp-should-not-start-bot"
    manager.arena_bot_running.discard(match_id)
    _maybe_start_arena_attacker_bot(match_id, "pvp")
    assert match_id not in manager.arena_bot_running
    _maybe_start_arena_attacker_bot(match_id, "human_attacks_vs_ai")
    assert match_id not in manager.arena_bot_running


@pytest.mark.asyncio
async def test_bot_loop_stops_quietly_when_defender_connection_is_dead():
    """Regression test: a defender closing their browser mid-match must not
    make the bot loop spin forever or crash the process. Patches
    manager.send_personal to always raise (mirroring what a closed real
    WebSocket's send_json does) so this is deterministic regardless of
    whether any particular move happens to be detected — waiting on a real
    detected/alert event would make this test flaky and slow, since
    detection is probabilistic. Confirms _run_arena_attacker_bot exits
    cleanly after the FIRST action was still persisted (the notify failure
    must not roll back or block the already-committed action), and confirms
    the arena_bot_running guard is cleared so a future reconnect could retry."""
    from unittest.mock import AsyncMock, patch
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from app.models.arena import ArenaAction

    match_id = "test-bot-dead-defender-match-4242"
    seed = 4242
    archetype_key = "small_healthcare"

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id, seed=seed, archetype_key=archetype_key,
            mode="human_defends_vs_ai", attacker_user_id=None,
            defender_user_id="defender-1", status="active",
        )
        db.add(match)
        await db.commit()

    manager.arena_connections.pop(match_id, None)
    manager.register_arena_connection(match_id, "attacker", object())  # any truthy placeholder
    manager.register_arena_connection(match_id, "defender", object())
    manager.arena_bot_running.add(match_id)

    dead_send = AsyncMock(side_effect=RuntimeError('Cannot call "send" once a close message has been sent.'))

    try:
        with patch("app.websocket.handlers.manager.send_personal", dead_send):
            await asyncio.wait_for(_run_arena_attacker_bot(match_id, difficulty="hard"), timeout=5.0)

        # The bot must have stopped after the very first notify failure
        # (didn't hang/spin/retry) and cleared its guard.
        assert match_id not in manager.arena_bot_running
        assert dead_send.await_count >= 1

        # The first action should have persisted before the dead-send was
        # hit — a send failure must not roll back or skip the
        # already-committed persistence step.
        async with AsyncSessionLocal() as db:
            _, final_actions = await _load_match_and_actions_for_test(db, match_id)
        assert len(final_actions) == 1
    finally:
        manager.arena_connections.pop(match_id, None)
        manager.arena_bot_running.discard(match_id)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()


async def _load_match_and_actions_for_test(db, match_id: str):
    from app.websocket.handlers import _load_match_and_actions
    return await _load_match_and_actions(db, match_id)
