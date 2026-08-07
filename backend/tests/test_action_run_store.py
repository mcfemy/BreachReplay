"""
Tests for backend/app/services/action_run_store.py (Phase 2, Item 3 — the
in-process live-run store: start/apply/finalize lifecycle, the abandonment
sweep, and reconnect support via `get`).

Uses the real `db`/`test_user` fixtures (conftest.py) since finalize()
does real persistence (ActionRun rows, XP, achievements) — these are
integration tests, not pure-function tests like test_verb_engine.py.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.action_run import ActionRun
from app.models.scenario import Scenario
from app.models.user import User
from app.services import action_engine
from app.services.action_run_store import ActionRunStore, CAP_SECONDS_BY_MODE, SWEEP_GRACE_SECONDS

pytestmark = pytest.mark.asyncio

# A short final-stage trigger (+2m = 120s) so a legitimate, fast play
# sequence (isolate the target, then let a few cheap verbs burn clock time
# up to the trigger) can naturally conclude the run well inside
# xp_service's speed_demon threshold (<=300s) — see
# test_finalize_unlocks_perfect_analyst_and_speed_demon_on_a_realistic_fast_win.
_FAST_DECISION_TREE = [
    {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
     "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
]


@pytest.fixture
async def fast_scenario(db):
    scenario = Scenario(
        title="Fast Test Scenario",
        source_type="manual",
        source_reference="TEST-FAST-001",
        difficulty="practitioner",
        industry_vertical="energy",
        status="approved",
        decision_tree=_FAST_DECISION_TREE,
        # Pinned to 1.0 (no compression) — the "+2m" trigger above is chosen
        # as literal seconds against this file's own store/finalize timing
        # assertions, not to exercise action_engine's compression scaling
        # (covered separately by test_action_engine.py). Scenario.
        # compression_ratio defaults to 8.0 at the DB level, which would
        # otherwise compress +2m to 15s and fire the gate far earlier than
        # these tests assume.
        compression_ratio=1.0,
        alert_sequence=[],
    )
    db.add(scenario)
    await db.flush()
    return scenario


@pytest.fixture
def store():
    return ActionRunStore()


def _new_run_id() -> str:
    return str(uuid.uuid4())


async def test_start_run_and_get_round_trip(store, fast_scenario, test_user):
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()

    live = await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)
    assert live.run_state.elapsed_seconds == 0

    fetched = await store.get(run_id)
    assert fetched is live


async def test_get_returns_none_for_unknown_run_id(store):
    assert await store.get("not-a-real-run-id") is None


async def test_apply_verb_updates_the_stored_run_state_reconnect_sees_latest(store, fast_scenario, test_user):
    """This IS the reconnect guarantee: a second `get()` (simulating a
    fresh WS connection resuming an existing run_id) must see whatever the
    first connection already did, not a stale/fresh copy."""
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)

    result, is_over = await store.apply_verb(run_id, "scan_network", None)
    assert result.error is None
    assert is_over is False

    resumed = await store.get(run_id)
    assert resumed.run_state.elapsed_seconds == 45  # scan_network cost


async def test_apply_verb_raises_for_unknown_run_id(store):
    with pytest.raises(KeyError):
        await store.apply_verb("not-a-real-run-id", "scan_network", None)


async def test_finalize_persists_action_run_and_evicts_from_store(db, store, fast_scenario, test_user):
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)
    await store.apply_verb(run_id, "scan_network", None)

    summary = await store.finalize(db, run_id)
    assert summary is not None
    assert summary["outcome"] in (
        "contained", "contained_at_cost", "overreacted", "breached_spread_limited", "breached",
    )
    # The persisted row's id is deliberately the SAME as run_id (not an
    # independently-generated uuid4) — see finalize()'s ActionRun(id=...)
    # comment for why: a caller must be able to trust the id POST
    # /action-runs handed them up front, not discover a second "real" id
    # only via the run.end WS event.
    assert summary["action_run_id"] == run_id

    assert await store.get(run_id) is None  # evicted

    result = await db.execute(select(ActionRun).where(ActionRun.id == summary["action_run_id"]))
    row = result.scalar_one()
    assert row.user_id == test_user["user"].id
    assert row.scenario_id == fast_scenario.id
    assert row.duration_seconds == 45
    assert row.mode == "scenario"


async def test_finalize_returns_none_for_an_already_finalized_run(db, store, fast_scenario, test_user):
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)

    first = await store.finalize(db, run_id)
    assert first is not None
    second = await store.finalize(db, run_id)
    assert second is None


async def test_finalize_skips_xp_and_achievements_for_a_teaser_mode_run_with_no_user(db, store, fast_scenario):
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    await store.start_run(run_id, None, fast_scenario.id, "teaser", compiled)

    summary = await store.finalize(db, run_id)
    assert summary["xp_awarded"] == 0
    assert summary["new_achievements"] == []

    result = await db.execute(select(ActionRun).where(ActionRun.id == summary["action_run_id"]))
    row = result.scalar_one()
    assert row.user_id is None


async def test_finalize_unlocks_perfect_analyst_and_speed_demon_on_a_realistic_fast_win(db, store, fast_scenario, test_user):
    """The point of this test: play a REALISTIC sequence through the store
    (isolate the real attack-path target, then let a couple of cheap verbs
    burn clock time up to the final stage's trigger — exactly how a human
    player would actually finish this scenario fast and clean) and confirm
    xp_service.check_scenario_achievements — which has no other caller in
    the backend — actually unlocks perfect_analyst and speed_demon from
    that play, rather than asserting it in the abstract."""
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    final_stage = next(s for s in compiled.stages if s.is_final)
    target_host_id = final_stage.compromises_host_ids[0]

    run_id = _new_run_id()
    await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)

    result, is_over = await store.apply_verb(run_id, "isolate", target_host_id)
    assert result.error is None
    assert result.delta["on_attack_path"] is True  # a correct call, not a lucky guess

    # Burn clock time with clean (no-target, no-penalty) verbs until the
    # attacker's scheduled detonation moment has passed — naturally
    # concluding the run, exactly like real play.
    while not is_over:
        result, is_over = await store.apply_verb(run_id, "scan_network", None)
        assert result.error is None

    live = await store.get(run_id)
    assert live.run_state.elapsed_seconds <= 300, "test scenario must stay realistic/fast — under the speed_demon threshold"

    summary = await store.finalize(db, run_id)
    assert summary["outcome"] == "contained"
    assert summary["score_breakdown"]["score_pct"] == 100.0
    assert "perfect_analyst" in summary["new_achievements"]
    assert "speed_demon" in summary["new_achievements"]
    assert summary["xp_awarded"] > 0

    await db.refresh(test_user["user"])
    assert test_user["user"].xp_total > 0


async def test_sweep_expired_force_finalizes_abandoned_runs_as_breached(db, store, fast_scenario, test_user):
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    live = await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)

    # Backdate real_started_at past cap+grace — simulating a run abandoned
    # a long time ago (a real client would never actually wait this long;
    # this directly exercises the sweep's own time math).
    overdue = CAP_SECONDS_BY_MODE["scenario"] + SWEEP_GRACE_SECONDS + 5
    live.real_started_at = datetime.utcnow() - timedelta(seconds=overdue)

    finalized = await store.sweep_expired(db)
    finalized_ids = [run_id for run_id, _summary in finalized]
    assert run_id in finalized_ids
    assert await store.get(run_id) is None

    result = await db.execute(select(ActionRun).where(ActionRun.user_id == test_user["user"].id))
    row = result.scalar_one()
    assert row.outcome == "breached"  # forced, regardless of what determine_outcome would've said

    summary = dict(finalized)[run_id]
    assert summary["outcome"] == "breached"
    assert summary["action_run_id"] == row.id


async def test_sweep_expired_leaves_fresh_runs_alone(db, store, fast_scenario, test_user):
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)

    finalized = await store.sweep_expired(db)
    finalized_ids = [run_id for run_id, _summary in finalized]
    assert run_id not in finalized_ids
    assert await store.get(run_id) is not None


async def test_finalize_awards_zero_xp_and_no_achievements_for_an_overreacted_run(db, store, fast_scenario, test_user):
    """Proportionate Response's core acceptance case, at the store/finalize
    layer where XP is actually gated (not just verb_engine.determine_outcome
    in isolation): a player who isolates the real final target AND every
    other revealed host — the "scan once, isolate everything" exploit —
    must land on `overreacted` and get ZERO XP, zero achievements, even
    though the final target genuinely was stopped. seed=1 against
    fast_scenario compiles 13 hosts with only the final stage's target
    (host-9) on the attack path (confirmed by direct inspection), so
    isolating all 13 hosts isolates 12 of 12 available decoys — 100%
    coverage, well past the 60% egregious threshold."""
    compiled = action_engine.compile_scenario(fast_scenario, seed=1)
    run_id = _new_run_id()
    await store.start_run(run_id, test_user["user"].id, fast_scenario.id, "scenario", compiled)

    is_over = False
    for host in compiled.world.hosts:
        result, is_over = await store.apply_verb(run_id, "isolate", host.id)
        assert result.error is None

    # Isolating every host doesn't by itself guarantee crossing the final
    # stage's trigger — burn clock time with clean verbs until it fires,
    # same pattern as the realistic-fast-win test above.
    while not is_over:
        result, is_over = await store.apply_verb(run_id, "scan_network", None)
        assert result.error is None

    summary = await store.finalize(db, run_id)
    assert summary["outcome"] == "overreacted"
    assert summary["xp_awarded"] == 0
    assert summary["new_achievements"] == []

    await db.refresh(test_user["user"])
    assert test_user["user"].xp_total == 0
