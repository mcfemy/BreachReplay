"""Tests for Live Arena Mode Phase E: the deterministic AI defender policy
bot (app/services/arena_ai_defender.py) and its SYNCHRONOUS, in-lock
integration with the Phase C persistence path
(app/websocket/handlers.py's _execute_arena_action /
_apply_defender_bot_response_locked), mirroring test_arena_ai_attacker.py's
structure for Phase D.

Fairness-fix note: the AI defender's response used to be dispatched as a
detached `asyncio.create_task` from `_notify_arena_action_result`, whose
first step was `await asyncio.sleep(REACTION_DELAY_SECONDS)` BEFORE
acquiring the per-match lock and applying the response — the lock was not
held during that sleep, so an attacker's next WS message could always race
ahead of the defender's still-pending reaction. The fix moved the response's
computation AND persistence inside `_execute_arena_action`'s own locked
critical section, immediately after the triggering attacker action; only
the cosmetic notification (`_notify_arena_defender_bot_response`) still uses
`REACTION_DELAY_SECONDS`, purely for narrative pacing, well after the state
mutation is already committed. Tests below exercise the new synchronous
path via `_execute_arena_action`'s `result["defender_response"]`, and
`test_attacker_cannot_outrun_synchronous_defender_response` locks in the
core fairness property this fix guarantees.

Per the plan's Phase E verification requirements:
1. An AI-defender match (human_attacks_vs_ai) reaches a terminal state when
   driven by a scripted sequence of attacker actions with the defender bot
   reacting automatically — no human defender input.
2. Determinism: same trigger context + difficulty + rng seed -> identical
   chosen response across two runs.
3. Difficulty measurably changes outcomes: "hard" contains the attacker more
   effectively than "easy" across multiple seeds.
4. No global `random` usage anywhere in arena_ai_defender.py.
5. Dead-connection regression test (deterministic, mocked).
6. Regression test proving the race is closed (fairness-fix follow-up).
7/8. Full suite regression + py_compile (run separately, see report).
"""
import asyncio
import random
import re
from pathlib import Path

import pytest

from app.models.arena import ArenaMatch, ArenaAction
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    apply_attacker_action,
    apply_defender_action,
    generate_org_state,
    replay,
    _derive_rng,
)
from app.services.arena_ai_defender import choose_defender_action, REACTION_DELAY_SECONDS
from app.services.arena_ai_attacker import choose_attacker_action
from app.websocket.handlers import (
    _execute_arena_action,
    _decision_gate_trigger,
    _load_match_and_actions,
    _notify_arena_action_result,
)
from app.websocket.manager import manager

_MAX_STEPS = 200
_COMPROMISE_ORDER = {"none": 0, "foothold": 1, "admin": 2, "domain_admin": 3}


# ── 1. AI-defender match reaches a terminal state, driven purely by attacker
#      actions with the defender bot reacting automatically ─────────────────

def _drive_attacker_vs_ai_defender_pure(
    seed: int, archetype_key: str, attacker_difficulty: str, defender_difficulty: str, max_steps: int = _MAX_STEPS,
) -> tuple[object, list[dict]]:
    """Pure (no DB/WS) simulation of a full human_attacks_vs_ai match: the
    attacker bot picks a move, it's applied; if that move crosses a
    decision-gate threshold, the defender bot reacts immediately (exactly
    mirroring the reactive-synchronous design in handlers.py, just without
    persistence/notify side effects) before the attacker's next move.
    Returns (final_state, combined_action_log) so tests can assert both
    outcome and determinism without touching the DB.

    Stall guard: `choose_attacker_action` has no fog-of-war/attacker-
    knowledge memory of "already discovered this host" (a deliberate v1
    simplification per that module's own docstring) — a sufficiently
    effective defender bot can isolate or otherwise neutralize every host
    the attacker can escalate on, leaving the attacker permanently unable to
    make strategic progress (no viable gain_foothold/escalate_privilege/
    lateral_move/deploy_impact candidates) while `discover_host` candidates
    remain non-empty forever, so `choose_attacker_action` never legitimately
    returns `None`. A real human attacker in that situation would notice
    nothing is progressing and stop; this harness mirrors that by tracking a
    coarse STRATEGIC fingerprint of state (isolated-host count + sum of
    compromise levels across all hosts + harvested-credential count) over a
    trailing window of `_STALL_WINDOW` attacker actions, and stopping once
    that fingerprint hasn't changed for the whole window — i.e. "no
    containment-relevant progress happened in N consecutive moves", not
    merely "the exact same action repeated". This is a test-harness realism
    fix (making the scripted-attacker stand-in behave like a rational human
    who'd disengage from a fully-contained match), not a change to either
    policy module."""
    archetype = ORG_ARCHETYPES[archetype_key]
    state = generate_org_state(seed, archetype)
    combined_log: list[dict] = []
    step = 0
    attacker_moves_made = 0
    _STALL_WINDOW = 10

    def _strategic_fingerprint(s):
        compromise_sum = sum(_COMPROMISE_ORDER[h.compromise_level] for h in s.hosts)
        isolated_count = sum(1 for h in s.hosts if h.isolated)
        harvested_count = sum(1 for c in s.credentials if c.harvested)
        return (compromise_sum, isolated_count, harvested_count)

    recent_fingerprints: list[tuple] = []

    for _ in range(max_steps):
        rng = _derive_rng(seed, step)
        atk_action = choose_attacker_action(state, attacker_difficulty, rng, actions_taken=attacker_moves_made)
        if atk_action is None:
            break
        action_type = atk_action["action_type"]
        payload = atk_action["payload"]

        engine_rng = _derive_rng(seed, step)
        prev_state = state
        state, detected, alert = apply_attacker_action(
            state, {"action_type": action_type, "payload": payload, "sequence_number": step}, engine_rng
        )

        combined_log.append({"actor": "attacker", "action_type": action_type, "payload": payload})
        attacker_moves_made += 1
        step += 1

        recent_fingerprints.append(_strategic_fingerprint(state))
        if len(recent_fingerprints) > _STALL_WINDOW:
            recent_fingerprints.pop(0)
        if len(recent_fingerprints) == _STALL_WINDOW and len(set(recent_fingerprints)) == 1:
            break

        if state.global_flags.get("impact_deployed"):
            break

        gate_trigger = _decision_gate_trigger(action_type, payload, prev_state, state)
        if gate_trigger:
            reason, host_dict, credential_id = gate_trigger
            def_rng = _derive_rng(seed, step)
            def_action = choose_defender_action(state, reason, host_dict, credential_id, defender_difficulty, def_rng)
            if def_action is not None:
                combined_log.append({
                    "actor": "defender",
                    "action_type": def_action["action_type"],
                    "payload": def_action["payload"],
                })
                state = apply_defender_action(state, def_action)
                step += 1

    return state, combined_log


@pytest.mark.parametrize("seed", [1, 42, 999, 123456, 7])
@pytest.mark.parametrize("archetype_key", list(ORG_ARCHETYPES.keys()))
def test_attacker_vs_ai_defender_reaches_terminal_state(seed, archetype_key):
    """A human_attacks_vs_ai match (scripted attacker sequence standing in
    for a human, real defender bot reacting) always terminates within a
    reasonable step count, with no human defender input anywhere in the
    loop."""
    state, actions_log = _drive_attacker_vs_ai_defender_pure(seed, archetype_key, "hard", "medium")
    assert len(actions_log) > 0
    # Terminal: either impact was deployed (attacker won) or the attacker
    # ran out of viable moves (no infinite loop, no hang).
    attacker_actions = [a for a in actions_log if a["actor"] == "attacker"]
    assert len(attacker_actions) < _MAX_STEPS


def test_defender_bot_reacts_at_least_once_across_seeds():
    """Confirm the reactive defender bot actually fires (not just a no-op
    match where no decision gate is ever crossed) for at least some seeds —
    proves the reactive hook point is live, not dead code."""
    any_defender_action = False
    for seed in range(20):
        _, actions_log = _drive_attacker_vs_ai_defender_pure(seed, "energy_utility", "hard", "hard")
        if any(a["actor"] == "defender" for a in actions_log):
            any_defender_action = True
            break
    assert any_defender_action, "expected the AI defender bot to react at least once across a spread of seeds"


# ── 2. Determinism: identical trigger + difficulty + rng seed -> identical
#      chosen response ──────────────────────────────────────────────────────

def test_choose_defender_action_deterministic_same_inputs():
    archetype = ORG_ARCHETYPES["small_healthcare"]
    state = generate_org_state(7, archetype)
    host = state.hosts[0].to_dict()
    credential_id = state.credentials[0].id

    for difficulty in ("easy", "medium", "hard"):
        rng_a = random.Random(555)
        rng_b = random.Random(555)
        action_a = choose_defender_action(state, "Host reached admin-level compromise", host, credential_id, difficulty, rng_a)
        action_b = choose_defender_action(state, "Host reached admin-level compromise", host, credential_id, difficulty, rng_b)
        assert action_a == action_b


def test_full_match_defender_response_sequence_deterministic_same_seed():
    """End-to-end determinism: replaying the same (seed, archetype,
    attacker/defender difficulty) pair twice produces byte-identical combined
    action logs, mirroring test_arena_ai_attacker's
    test_bot_action_sequence_deterministic_same_seed_same_difficulty."""
    run_a_state, run_a_log = _drive_attacker_vs_ai_defender_pure(2024, "small_healthcare", "medium", "medium")
    run_b_state, run_b_log = _drive_attacker_vs_ai_defender_pure(2024, "small_healthcare", "medium", "medium")
    assert run_a_log == run_b_log
    assert run_a_state.to_dict() == run_b_state.to_dict()


# ── 3. Difficulty measurably changes outcomes ───────────────────────────────

def test_hard_defender_contains_attacker_better_than_easy_defender():
    """Across the same attacker action sequence (attacker difficulty held
    fixed at "hard" so both runs face an identical, strong opponent), a
    "hard" defender should on average contain the attacker more effectively
    than an "easy" defender: fewer matches reaching impact_deployed, and
    (for the ones that do) more defender actions taken / more hosts
    isolated on average. Asserts something concrete across multiple seeds,
    not just "it ran"."""
    hard_def_impact_count = 0
    easy_def_impact_count = 0
    hard_def_isolated_hosts_total = 0
    easy_def_isolated_hosts_total = 0

    num_seeds = 40
    for seed in range(num_seeds):
        hard_state, _ = _drive_attacker_vs_ai_defender_pure(seed, "energy_utility", "hard", "hard")
        easy_state, _ = _drive_attacker_vs_ai_defender_pure(seed, "energy_utility", "hard", "easy")

        if hard_state.global_flags.get("impact_deployed"):
            hard_def_impact_count += 1
        if easy_state.global_flags.get("impact_deployed"):
            easy_def_impact_count += 1

        hard_def_isolated_hosts_total += sum(1 for h in hard_state.hosts if h.isolated)
        easy_def_isolated_hosts_total += sum(1 for h in easy_state.hosts if h.isolated)

    # Concrete claims: hard defender should let the attacker win (reach
    # impact) no MORE often than easy defender, and should isolate hosts at
    # least as often in aggregate (its stronger, more decisive responses).
    assert hard_def_impact_count <= easy_def_impact_count, (
        f"expected hard defender to contain the attacker at least as often as easy "
        f"(hard impact count={hard_def_impact_count}, easy impact count={easy_def_impact_count})"
    )
    assert hard_def_isolated_hosts_total >= easy_def_isolated_hosts_total, (
        f"expected hard defender to isolate hosts at least as often in aggregate "
        f"(hard total={hard_def_isolated_hosts_total}, easy total={easy_def_isolated_hosts_total})"
    )
    # And at least one of the two signals must show a REAL (strict) gap,
    # otherwise difficulty isn't measurably doing anything.
    assert (hard_def_impact_count < easy_def_impact_count) or (
        hard_def_isolated_hosts_total > easy_def_isolated_hosts_total
    ), "expected a strict difference between hard and easy defender outcomes across this seed sample"


def test_hard_defender_reaction_delay_faster_than_easy():
    assert REACTION_DELAY_SECONDS["hard"] < REACTION_DELAY_SECONDS["medium"] < REACTION_DELAY_SECONDS["easy"]


def test_hard_defender_always_isolates_host_on_admin_compromise_trigger():
    """A concrete, single-decision check of the policy's core claim: given a
    trigger context describing a host that just reached admin-level
    compromise (with both a host and a credential available), "hard" should
    reliably pick isolate_host (the objectively strong response), not a
    weaker one, across many rng states."""
    archetype = ORG_ARCHETYPES["small_healthcare"]
    state = generate_org_state(3, archetype)
    host = state.hosts[0].to_dict()
    credential_id = state.credentials[0].id

    for seed in range(30):
        rng = random.Random(seed)
        action = choose_defender_action(state, "Host reached admin-level compromise", host, credential_id, "hard", rng)
        assert action["action_type"] == "isolate_host"


def test_easy_defender_sometimes_picks_a_weaker_response():
    """"easy" should sometimes pick a weaker response (acknowledge/monitor
    instead of isolate) even when isolate_host is available and would be the
    strong choice — proves noise/narrow-pool behavior is real, not just
    theoretical."""
    archetype = ORG_ARCHETYPES["small_healthcare"]
    state = generate_org_state(3, archetype)
    host = state.hosts[0].to_dict()
    credential_id = state.credentials[0].id

    chosen_types = set()
    for seed in range(60):
        rng = random.Random(seed * 97 + 13)
        action = choose_defender_action(state, "Host reached admin-level compromise", host, credential_id, "easy", rng)
        chosen_types.add(action["action_type"])

    assert "isolate_host" in chosen_types
    assert len(chosen_types) > 1, f"expected easy defender to sometimes pick something other than isolate_host, got only {chosen_types}"


# ── 4. No global `random` module usage ──────────────────────────────────────

def test_no_global_random_module_usage_in_arena_ai_defender():
    source_path = Path(__file__).parent.parent / "app" / "services" / "arena_ai_defender.py"
    source = source_path.read_text()

    forbidden_pattern = re.compile(r"\brandom\.(random|choice|randint|sample|shuffle|uniform)\s*\(")
    hits = forbidden_pattern.findall(source)
    assert hits == [], f"found direct global `random.*` calls in arena_ai_defender.py: {hits}"

    rng_pattern = re.compile(r"\brng\.(random|choice|randint|sample|shuffle|uniform)\s*\(")
    assert rng_pattern.search(source), "expected at least one rng.<method>(...) call using the passed-in random.Random instance"


# ── 5. Integration: synchronous in-lock defender response through the real
#      persistence path ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reactive_defender_bot_responds_via_execute_arena_action():
    """A real human_attacks_vs_ai match: a scripted attacker action sequence
    is submitted through _execute_arena_action exactly as a human attacker's
    WS messages would be. Under the fairness fix, _execute_arena_action
    itself detects the decision-gate trigger and applies + persists the AI
    defender's response SYNCHRONOUSLY, inside the same call/critical section
    as the triggering attacker action — no separate function call needed,
    and `result["defender_response"]` reports what happened. Confirms a
    real defender ArenaAction row is persisted through the same
    _execute_arena_action path a human's defender_action WS message would
    use."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from tests.conftest import ensure_test_user_row

    match_id = "test-defender-bot-reactive-match-9001"
    seed = 9001
    archetype_key = "energy_utility"

    # attacker_user_id="attacker-1" below is a real ForeignKey("users.id")
    # column enforced immediately (not deferred) by Postgres — ensure the
    # backing row exists first (see conftest.py's ensure_test_user_row
    # docstring for the full explanation).
    await ensure_test_user_row("attacker-1")

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id, seed=seed, archetype_key=archetype_key,
            mode="human_attacks_vs_ai", attacker_user_id="attacker-1",
            defender_user_id=None, status="active",
        )
        db.add(match)
        await db.commit()

    try:
        state = generate_org_state(seed, ORG_ARCHETYPES[archetype_key])
        gate_fired = False
        for step in range(60):
            rng = _derive_rng(seed, step)
            atk_action = choose_attacker_action(state, "hard", rng, actions_taken=step)
            if atk_action is None:
                break
            action_type = atk_action["action_type"]
            payload = atk_action["payload"]

            result = await _execute_arena_action(match_id, "attacker", action_type, payload)
            assert result is not None
            state = result["new_state"]

            if result["defender_response"] is not None:
                gate_fired = True
                assert result["defender_response"]["action_type"] in (
                    "isolate_host", "disable_credential", "increase_monitoring", "acknowledge",
                )
                break

            if result["match_completed"]:
                break

        assert gate_fired, "expected at least one decision-gate trigger within the step budget for this seed/archetype"

        async with AsyncSessionLocal() as db:
            _, final_actions = await _load_match_and_actions(db, match_id)
        defender_rows = [a for a in final_actions if a["actor"] == "defender"]
        assert len(defender_rows) == 1
        assert defender_rows[0]["action_type"] in ("isolate_host", "disable_credential", "increase_monitoring", "acknowledge")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()
        manager.arena_defender_bot_responses.pop(match_id, None)


@pytest.mark.asyncio
async def test_full_ai_defender_match_reaches_terminal_status_via_real_persistence():
    """Drives a full human_attacks_vs_ai match end-to-end through the real
    _execute_arena_action path (scripted attacker sequence standing in for a
    human attacker's WS messages) until the match reaches a terminal
    ArenaMatch.status — no human defender input anywhere, and no separate
    defender-bot call needed: under the fairness fix, _execute_arena_action
    itself synchronously applies the AI defender's response, in-lock,
    immediately after any attacker action that crosses a decision-gate
    threshold. Mirrors test_arena_ai_attacker.py's
    test_bot_loop_drives_match_to_completion_via_execute_arena_action for
    the defender side."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from tests.conftest import ensure_test_user_row

    match_id = "test-full-ai-defender-match-31338"
    seed = 31338
    archetype_key = "small_healthcare"

    await ensure_test_user_row("attacker-1")

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id, seed=seed, archetype_key=archetype_key,
            mode="human_attacks_vs_ai", attacker_user_id="attacker-1",
            defender_user_id=None, status="active",
        )
        db.add(match)
        await db.commit()

    def _strategic_fingerprint(s):
        compromise_sum = sum(_COMPROMISE_ORDER[h.compromise_level] for h in s.hosts)
        isolated_count = sum(1 for h in s.hosts if h.isolated)
        harvested_count = sum(1 for c in s.credentials if c.harvested)
        return (compromise_sum, isolated_count, harvested_count)

    try:
        match_completed = False
        attacker_moves_made = 0
        # Stall guard: see _drive_attacker_vs_ai_defender_pure's docstring —
        # once a "hard" defender isolates every compromised host, the
        # attacker bot's candidate filtering can keep re-proposing
        # discover_host/lateral_move moves that are real no-ops (unreachable
        # segment / already fully explored), so choose_attacker_action never
        # legitimately returns None. A real human attacker would notice
        # nothing is progressing and stop; mirror that with the same
        # trailing-window strategic-fingerprint check used by
        # _drive_attacker_vs_ai_defender_pure, instead of spinning to
        # _MAX_STEPS on a fully-contained match.
        _STALL_WINDOW = 10
        recent_fingerprints: list[tuple] = []
        for _ in range(_MAX_STEPS):
            async with AsyncSessionLocal() as db:
                m, action_dicts = await _load_match_and_actions(db, match_id)
            if not m or m.status not in ("active", "lobby"):
                match_completed = m.status != "active" if m else True
                break

            state, _ = replay(m.seed, m.archetype_key, action_dicts)
            rng = _derive_rng(m.seed, len(action_dicts))
            atk_action = choose_attacker_action(state, "hard", rng, actions_taken=attacker_moves_made)
            if atk_action is None:
                break
            action_type = atk_action["action_type"]
            payload = atk_action["payload"]

            result = await _execute_arena_action(match_id, "attacker", action_type, payload)
            assert result is not None
            attacker_moves_made += 1
            new_state = result["new_state"]

            recent_fingerprints.append(_strategic_fingerprint(new_state))
            if len(recent_fingerprints) > _STALL_WINDOW:
                recent_fingerprints.pop(0)
            if len(recent_fingerprints) == _STALL_WINDOW and len(set(recent_fingerprints)) == 1:
                break

            if result["match_completed"]:
                match_completed = True
                break

            # No separate defender-bot call needed here anymore —
            # _execute_arena_action already applied+persisted the AI
            # defender's response synchronously above if `action_type`
            # crossed a decision-gate threshold (see result["defender_response"]).

        async with AsyncSessionLocal() as db:
            final_match, final_actions = await _load_match_and_actions(db, match_id)

        # Terminal by this test's definition: either the match's own status
        # flipped (attacker_won), or the attacker ran out of viable/
        # productive moves (None returned, or the stall guard tripped) —
        # either way, no infinite loop / no hang, and the defender bot must
        # have actually participated.
        assert match_completed or final_match.status != "active" or len(recent_fingerprints) == _STALL_WINDOW
        assert len(final_actions) > 0
        assert any(a["actor"] == "defender" for a in final_actions), (
            "expected the reactive AI defender bot to have submitted at least one response over the course of the match"
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()
        manager.arena_defender_bot_responses.pop(match_id, None)


# ── 5b. Dead-connection regression test (deterministic, mocked) ────────────

@pytest.mark.asyncio
async def test_defender_bot_response_survives_dead_attacker_connection():
    """Regression test mirroring test_arena_ai_attacker.py's
    test_bot_loop_stops_quietly_when_defender_connection_is_dead: an
    attacker closing their browser right as the AI defender bot's
    (already-persisted, synchronous) response is being NOTIFIED must not
    crash the process or roll back the already-persisted defender action.

    Under the fairness fix, persistence (_execute_arena_action) and
    notification (_notify_arena_defender_bot_response, the cosmetic-only
    function `_notify_arena_action_result` dispatches via
    `asyncio.create_task` once it sees `result["defender_response"]` is
    set) are two fully separate steps. This test drives the triggering
    attacker action through the real _execute_arena_action (which
    synchronously persists the defender's response inside the lock,
    unaffected by any WS mocking), then calls
    _notify_arena_defender_bot_response directly with manager.send_personal
    patched to always raise (mirroring what a closed real WebSocket's
    send_json does) and confirms it swallows the exception (its own
    try/except, mirroring _run_arena_attacker_bot's identical broad catch)
    without rolling back or skipping the already-committed persistence."""
    from unittest.mock import AsyncMock, patch
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from app.websocket.handlers import _notify_arena_defender_bot_response
    from tests.conftest import ensure_test_user_row

    match_id = "test-defender-bot-dead-attacker-match-5252"
    seed = 5252
    archetype_key = "energy_utility"

    await ensure_test_user_row("attacker-1")

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id, seed=seed, archetype_key=archetype_key,
            mode="human_attacks_vs_ai", attacker_user_id="attacker-1",
            defender_user_id=None, status="active",
        )
        db.add(match)
        await db.commit()

    manager.arena_connections.pop(match_id, None)
    manager.register_arena_connection(match_id, "attacker", object())  # any truthy placeholder
    manager.arena_defender_bot_responses.pop(match_id, None)

    dead_send = AsyncMock(side_effect=RuntimeError('Cannot call "send" once a close message has been sent.'))

    try:
        state = generate_org_state(seed, ORG_ARCHETYPES[archetype_key])
        result = None
        for step in range(60):
            rng = _derive_rng(seed, step)
            atk_action = choose_attacker_action(state, "hard", rng, actions_taken=step)
            if atk_action is None:
                break
            action_type = atk_action["action_type"]
            payload = atk_action["payload"]

            result = await _execute_arena_action(match_id, "attacker", action_type, payload)
            assert result is not None
            state = result["new_state"]
            if result["defender_response"] is not None:
                break
            if state.global_flags.get("impact_deployed"):
                break

        assert result is not None and result["defender_response"] is not None, (
            "expected at least one decision-gate trigger (and synchronous defender response) "
            "within the step budget for this seed/archetype"
        )
        # The defender action is already persisted at this point — nothing
        # about the notify step below can affect that.

        with patch("app.websocket.handlers.manager.send_personal", dead_send):
            await asyncio.wait_for(
                _notify_arena_defender_bot_response(match_id, result["defender_response"]),
                timeout=5.0,
            )

        # The defender action must remain persisted regardless of the dead
        # notify — a notify failure must not roll back or skip the
        # already-committed persistence step.
        async with AsyncSessionLocal() as db:
            _, final_actions = await _load_match_and_actions(db, match_id)
        defender_rows = [a for a in final_actions if a["actor"] == "defender"]
        assert len(defender_rows) == 1
        # The dead connection must have actually been exercised (proves this
        # test is really exercising the failure path, not silently no-op'ing).
        assert dead_send.await_count >= 1
    finally:
        manager.arena_connections.pop(match_id, None)
        manager.arena_defender_bot_responses.pop(match_id, None)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()


@pytest.mark.asyncio
async def test_defender_bot_response_ceiling_stops_reacting():
    """The _MAX_DEFENDER_BOT_RESPONSES ceiling (defense-in-depth mirroring
    _MAX_BOT_STEPS) must actually stop the bot from submitting a new
    response once hit, deterministically (no need to actually drive hundreds
    of real triggers — directly pre-seed manager.arena_defender_bot_responses
    at the ceiling). Under the fairness fix the ceiling check now lives
    inside _apply_defender_bot_response_locked, itself called from
    _execute_arena_action's own locked critical section (no longer a
    separately-callable reactive function) — so this test drives a real
    decision-gate-triggering attacker action through _execute_arena_action
    and confirms ONLY the attacker's action persists (no defender
    ArenaAction row), proving the ceiling is honored even though the
    ceiling check/increment is no longer a racy check-then-act pattern (it's
    now serialised by the per-match lock, like everything else in that
    critical section)."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from app.websocket.handlers import _MAX_DEFENDER_BOT_RESPONSES, _decision_gate_trigger
    from tests.conftest import ensure_test_user_row

    match_id = "test-defender-bot-ceiling-match-6161"
    seed = 6161
    archetype_key = "small_healthcare"

    await ensure_test_user_row("attacker-1")

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id, seed=seed, archetype_key=archetype_key,
            mode="human_attacks_vs_ai", attacker_user_id="attacker-1",
            defender_user_id=None, status="active",
        )
        db.add(match)
        await db.commit()

    manager.arena_defender_bot_responses[match_id] = _MAX_DEFENDER_BOT_RESPONSES

    try:
        state = generate_org_state(seed, ORG_ARCHETYPES[archetype_key])
        gate_fired = False
        for step in range(60):
            rng = _derive_rng(seed, step)
            atk_action = choose_attacker_action(state, "hard", rng, actions_taken=step)
            if atk_action is None:
                break
            action_type = atk_action["action_type"]
            payload = atk_action["payload"]

            prev_state = state
            result = await asyncio.wait_for(
                _execute_arena_action(match_id, "attacker", action_type, payload), timeout=5.0,
            )
            assert result is not None
            state = result["new_state"]

            if _decision_gate_trigger(action_type, payload, prev_state, state):
                gate_fired = True
                # The ceiling was already at _MAX_DEFENDER_BOT_RESPONSES
                # before this call, so even though a gate fired,
                # _execute_arena_action must NOT have applied/persisted a
                # defender response for it.
                assert result["defender_response"] is None, (
                    "expected the response ceiling to prevent a new defender action even though a gate fired"
                )
                break

            if result["match_completed"]:
                break

        assert gate_fired, "expected at least one decision-gate trigger within the step budget for this seed/archetype"

        async with AsyncSessionLocal() as db:
            _, final_actions = await _load_match_and_actions(db, match_id)
        defender_rows = [a for a in final_actions if a["actor"] == "defender"]
        assert defender_rows == [], "expected the ceiling to prevent any new defender action from being persisted"
        # The counter must not have been bumped past the ceiling either.
        assert manager.arena_defender_bot_responses[match_id] == _MAX_DEFENDER_BOT_RESPONSES
    finally:
        manager.arena_defender_bot_responses.pop(match_id, None)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()


# ── 6. Regression: the race is closed — an attacker cannot outrun the
#      synchronous in-lock defender response ────────────────────────────────

@pytest.mark.asyncio
async def test_attacker_cannot_outrun_synchronous_defender_response():
    """THE core fairness property this fix guarantees, proven end-to-end
    through the real _execute_arena_action persistence path (no mocked
    timing, no sleeps to race against — the whole point is that there is
    nothing left to race).

    Drives a real human_attacks_vs_ai match with a scripted 'hard' attacker
    until an attacker action crosses a decision-gate threshold AND the AI
    defender's synchronous response is 'isolate_host' (the objectively
    strong response 'hard' reliably picks per
    test_hard_defender_always_isolates_host_on_admin_compromise_trigger).
    The instant _execute_arena_action returns — with NO sleep, NO delay, NO
    yield to any other coroutine in between, exactly mirroring an attacker
    WS loop immediately back at receive_text() — submits a FOLLOW-UP
    attacker action (escalate_privilege) targeting the SAME host that was
    just isolated.

    Under the OLD fire-and-forget/sleep-then-act design, this follow-up
    would race ahead of the (still-sleeping, lock-free) defender bot task
    and be evaluated against PRE-containment state — succeeding when it
    should have failed, every time, for any attacker acting at a normal or
    fast pace. Under the FIXED design, the defender's isolate_host is
    already committed before _execute_arena_action's lock was ever
    released, so the follow-up escalate_privilege is evaluated against
    POST-containment reality: `org_simulation.apply_attacker_action`'s
    escalate_privilege branch explicitly no-ops when `host.isolated` is
    True (returns state unchanged, detected=False) — so the follow-up must
    have zero effect and there must be exactly one ArenaAction row touching
    that host's compromise level (the original escalation), not two."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from tests.conftest import ensure_test_user_row

    match_id = "test-attacker-cannot-outrun-defender-match-7373"
    seed = 7373
    archetype_key = "small_healthcare"

    await ensure_test_user_row("attacker-1")

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
        await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
        match = ArenaMatch(
            id=match_id, seed=seed, archetype_key=archetype_key,
            mode="human_attacks_vs_ai", attacker_user_id="attacker-1",
            defender_user_id=None, status="active",
        )
        db.add(match)
        await db.commit()

    try:
        state = generate_org_state(seed, ORG_ARCHETYPES[archetype_key])
        isolated_host_id = None
        for step in range(80):
            rng = _derive_rng(seed, step)
            atk_action = choose_attacker_action(state, "hard", rng, actions_taken=step)
            if atk_action is None:
                break
            action_type = atk_action["action_type"]
            payload = atk_action["payload"]

            result = await _execute_arena_action(match_id, "attacker", action_type, payload)
            assert result is not None
            state = result["new_state"]

            defender_response = result["defender_response"]
            if defender_response is not None and defender_response["action_type"] == "isolate_host":
                isolated_host_id = defender_response["payload"]["host_id"]
                # Confirm the isolation is ALREADY reflected in the state
                # _execute_arena_action just returned — no sleep happened
                # anywhere above, this assertion runs on the very next line
                # after the call that persisted it.
                isolated_host = state.get_host(isolated_host_id)
                assert isolated_host is not None and isolated_host.isolated is True
                break

            if result["match_completed"]:
                break

        assert isolated_host_id is not None, (
            "expected at least one decision-gate trigger with an isolate_host defender response "
            "within the step budget for this seed/archetype"
        )

        # THE race check: submit a follow-up attacker action against the
        # now-isolated host immediately — no asyncio.sleep, no yield, this
        # call happens on the very next line, exactly like an attacker WS
        # loop's next receive_text() would.
        from sqlalchemy import select as _select

        async with AsyncSessionLocal() as db:
            match_row = (await db.execute(_select(ArenaMatch).where(ArenaMatch.id == match_id))).scalar_one()
        # Phase H: the isolate_host action that just fired may itself have
        # achieved full defender containment (check_defender_containment),
        # ending the match right there. That's an even stronger proof of
        # "the attacker cannot outrun the defender" than the original race
        # check — the match is already over before the attacker's next
        # action can even be evaluated, so _execute_arena_action correctly
        # returns None for it (no playable match to act against).
        match_already_completed = match_row.status != "active"

        pre_followup_state = state
        followup_result = await _execute_arena_action(
            match_id, "attacker", "escalate_privilege", {"host_id": isolated_host_id},
        )

        if match_already_completed:
            assert followup_result is None
        else:
            assert followup_result is not None

            followup_host = followup_result["new_state"].get_host(isolated_host_id)
            assert followup_host is not None
            # The core assertion: isolation holds, and the follow-up action had
            # NO effect on that host's compromise level (org_simulation's
            # escalate_privilege branch no-ops entirely on an isolated host).
            assert followup_host.isolated is True
            assert followup_host.compromise_level == pre_followup_state.get_host(isolated_host_id).compromise_level
            assert followup_result["detected"] is False

        # And at the persistence level: the defender's isolate_host row for
        # this host exists exactly once, and if the follow-up attacker
        # action was actually processed (match wasn't already over), it's
        # persisted strictly AFTER that isolate_host row — never interleaved
        # with or preceded by a second, earlier attacker action that snuck
        # in before containment.
        async with AsyncSessionLocal() as db:
            _, final_actions = await _load_match_and_actions(db, match_id)
        isolate_rows = [
            a for a in final_actions
            if a["actor"] == "defender" and a["action_type"] == "isolate_host"
            and a["payload"].get("host_id") == isolated_host_id
        ]
        assert len(isolate_rows) == 1
        isolate_seq = isolate_rows[0]["sequence_number"]
        followup_rows = [
            a for a in final_actions
            if a["actor"] == "attacker" and a["action_type"] == "escalate_privilege"
            and a["payload"].get("host_id") == isolated_host_id
            and a["sequence_number"] > isolate_seq
        ]
        if match_already_completed:
            assert len(followup_rows) == 0, (
                "match was already over — the follow-up attacker action must not have been "
                "persisted at all"
            )
        else:
            assert len(followup_rows) == 1, (
                "expected the follow-up escalate_privilege action to be persisted strictly AFTER "
                "the defender's isolate_host action — proving no attacker action could ever land "
                "between the trigger and the (now-synchronous) containment"
            )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()
        manager.arena_defender_bot_responses.pop(match_id, None)


# ── 7. Resource-hygiene: per-match bookkeeping is cleaned up on terminal
#      status ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_arena_match_bookkeeping_cleaned_up_on_terminal_status():
    """Low-severity resource-hygiene fix (review finding): manager.arena_match_locks
    and manager.arena_defender_bot_responses must not leak a per-match entry
    forever once a match reaches a terminal status. Drives a real
    human_attacks_vs_ai match to attacker_won via deploy_impact and confirms
    both dicts no longer carry an entry for this match_id afterwards."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import delete
    from tests.conftest import ensure_test_user_row

    # Reuses test_arena_ai_attacker.py's known-good
    # (seed=31337, archetype="small_healthcare") pair for a
    # human_defends_vs_ai match, which that test confirms reliably reaches
    # attacker_won (an unopposed "hard" attacker bot, no defender bot in
    # this mode) — sidesteps any uncertainty about whether a given
    # human_attacks_vs_ai seed's AI defender manages to fully contain the
    # attacker within a step budget, which isn't what this test is about.
    match_id = "test-arena-cleanup-on-terminal-match-8484"
    seed = 31337
    archetype_key = "small_healthcare"

    await ensure_test_user_row("defender-1")

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

    try:
        state = generate_org_state(seed, ORG_ARCHETYPES[archetype_key])
        match_completed = False
        for step in range(_MAX_STEPS):
            rng = _derive_rng(seed, step)
            atk_action = choose_attacker_action(state, "hard", rng, actions_taken=step)
            if atk_action is None:
                break
            action_type = atk_action["action_type"]
            payload = atk_action["payload"]

            result = await _execute_arena_action(match_id, "attacker", action_type, payload)
            assert result is not None
            state = result["new_state"]
            if result["match_completed"]:
                # The lock/counter entries are cleaned up as part of THIS
                # same call, the instant match_completed flips True — so
                # asserting their presence must happen on a step BEFORE
                # this one (see the assertion right before this loop
                # starts), not here.
                match_completed = True
                break
            # Touch the lock/counter so there's something to clean up (proves
            # this test isn't vacuously true because nothing was ever created)
            # — only meaningful pre-completion, since cleanup fires exactly
            # when match_completed flips True, above.
            assert match_id in manager.arena_match_locks

        assert match_completed, "expected this scripted seed/archetype to reach attacker_won within the step budget"

        assert match_id not in manager.arena_match_locks, (
            "expected arena_match_locks' entry for a terminal match to be cleaned up"
        )
        assert match_id not in manager.arena_defender_bot_responses, (
            "expected arena_defender_bot_responses' entry for a terminal match to be cleaned up"
        )
    finally:
        manager.arena_match_locks.pop(match_id, None)
        manager.arena_defender_bot_responses.pop(match_id, None)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ArenaAction).where(ArenaAction.match_id == match_id))
            await db.execute(delete(ArenaMatch).where(ArenaMatch.id == match_id))
            await db.commit()
