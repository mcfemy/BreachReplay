"""
Tests for Phase 2 Item 4 — Daily Breach action mode
(backend/app/api/routes/daily.py's `/action-run` and
`/action-leaderboard/{id}` routes, `_deterministic_daily_seed`,
`record_daily_action_run_result`).

Two testing layers, matching existing precedent:
  - REST-layer tests (`POST /daily/action-run`, `GET
    /daily/action-leaderboard/{id}`) use the `client`/`db` fixtures from
    conftest.py — an isolated, always-rolled-back transaction, the same
    one test_action_runs_rest.py uses.
  - Anything that goes through `action_run_ws_handler` -> `finalize()` ->
    `record_daily_action_run_result()` uses `app.db.session.AsyncSessionLocal`
    directly instead, per test_action_run_ws_handler.py's documented
    reasoning: finalize() opens its own AsyncSessionLocal() session, a
    different connection than the `db` fixture's rolled-back one — writes
    made only through `db` would be invisible to it. Because
    AsyncSessionLocal-based writes are real, non-rolled-back commits that
    persist for the rest of the pytest session (a pre-existing test-infra
    property, see conftest.py's dispose_app_engine_pool_after_test
    docstring), every such test below uses a unique user_id and a unique
    (fake, future) challenge_date to stay isolated from the rest of the
    suite — including from `_update_streak`'s real-today-date idempotency
    guard, which only resets at real calendar midnight.
"""
import uuid
from datetime import date

from fastapi import WebSocketDisconnect

from app.api.routes.daily import _deterministic_daily_seed, record_daily_action_run_result
from app.services import action_engine
from app.services.action_run_store import action_run_store
from app.websocket.handlers import action_run_ws_handler

# No module-level `pytestmark = pytest.mark.asyncio` here (unlike this
# suite's other test_*.py files) — pytest.ini's asyncio_mode=auto already
# detects async def tests automatically, and this file, unlike those
# others, also has plain sync tests (the _deterministic_daily_seed unit
# tests below) that a blanket module mark would spuriously tag.


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class FakeWebSocket:
    """Same minimal double as test_action_run_ws_handler.py's — identical
    shape, action_run_ws_handler only ever calls .send_json/.receive_text/
    .close on it."""

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


# A single gate at +15m (900s) — well past the daily cap (480s), so a run
# that ends at ~495s can only have ended via the CAP condition, never
# because the final stage fired first.
_SLOW_DECISION_TREE = [
    {"id": "gate-001", "trigger_timestamp": "+15m", "mitre_technique": "T1078",
     "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
]


async def _make_scenario() -> "Scenario":
    from app.db.session import AsyncSessionLocal
    from app.models.scenario import Scenario

    async with AsyncSessionLocal() as db:
        scenario = Scenario(
            id=str(uuid.uuid4()),
            title="Daily Action Mode Test Scenario",
            source_type="manual",
            source_reference=f"TEST-DAILY-{uuid.uuid4().hex[:8]}",
            difficulty="practitioner",
            industry_vertical="energy",
            status="approved",
            decision_tree=_SLOW_DECISION_TREE,
            alert_sequence=[],
        )
        db.add(scenario)
        await db.commit()
        await db.refresh(scenario)
        return scenario


async def _make_daily_challenge(scenario_id: str, challenge_date: date, challenge_number: int = 1) -> "DailyChallenge":
    from app.db.session import AsyncSessionLocal
    from app.models.daily_challenge import DailyChallenge

    async with AsyncSessionLocal() as db:
        challenge = DailyChallenge(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            challenge_date=challenge_date,
            challenge_number=challenge_number,
        )
        db.add(challenge)
        await db.commit()
        await db.refresh(challenge)
        return challenge


# ── _deterministic_daily_seed ───────────────────────────────────────────────────

def test_deterministic_daily_seed_is_stable_for_the_same_date_and_scenario():
    seed1 = _deterministic_daily_seed(date(2030, 1, 1), "scenario-abc")
    seed2 = _deterministic_daily_seed(date(2030, 1, 1), "scenario-abc")
    assert seed1 == seed2


def test_deterministic_daily_seed_differs_across_dates_and_scenarios():
    base = _deterministic_daily_seed(date(2030, 1, 1), "scenario-abc")
    diff_date = _deterministic_daily_seed(date(2030, 1, 2), "scenario-abc")
    diff_scenario = _deterministic_daily_seed(date(2030, 1, 1), "scenario-xyz")
    assert base != diff_date
    assert base != diff_scenario


def test_deterministic_daily_seed_is_a_valid_compile_scenario_seed():
    seed = _deterministic_daily_seed(date(2030, 1, 1), "scenario-abc")
    assert isinstance(seed, int)
    assert 0 <= seed < 2**31 - 1


# ── POST /daily/action-run (REST layer) ─────────────────────────────────────────

async def test_create_daily_action_run_returns_a_live_daily_run(client, test_user, approved_scenario):
    resp = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    assert resp.status_code == 201
    body = resp.json()
    assert body["mode"] == "daily"
    assert body["cap_seconds"] == 480
    assert isinstance(body["seed"], int)
    assert body["daily_challenge_id"]

    live = await action_run_store.get(body["run_id"])
    assert live is not None
    assert live.mode == "daily"
    assert live.daily_challenge_id == body["daily_challenge_id"]

    async with action_run_store._lock:
        action_run_store._runs.pop(body["run_id"], None)


async def test_create_daily_action_run_requires_authentication(client):
    resp = await client.post("/api/v1/daily/action-run")
    assert resp.status_code == 403


async def test_two_players_get_the_same_shared_daily_seed_and_scenario(client, test_user, admin_user, approved_scenario):
    first = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    second = await client.post("/api/v1/daily/action-run", headers=_auth_headers(admin_user["token"]))
    assert first.status_code == 201
    assert second.status_code == 201

    first_body, second_body = first.json(), second.json()
    assert first_body["daily_challenge_id"] == second_body["daily_challenge_id"]
    assert first_body["scenario_id"] == second_body["scenario_id"]
    assert first_body["seed"] == second_body["seed"]

    async with action_run_store._lock:
        action_run_store._runs.pop(first_body["run_id"], None)
        action_run_store._runs.pop(second_body["run_id"], None)


async def test_create_daily_action_run_conflicts_for_a_second_attempt_the_same_day(client, db, test_user, approved_scenario):
    from app.models.action_run import ActionRun

    first = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    assert first.status_code == 201
    body = first.json()

    # Simulate that run having already completed — finalize() would
    # normally be the one writing this row (see the WS-handler-level
    # tests below); this is a REST-layer test using the isolated
    # `db`/`client` fixture session, so write it directly instead. Must
    # also evict the live run from the store the same way finalize()
    # itself does (pop-then-persist) — otherwise the live-run lookup
    # (added for the double-POST fix below) would see this run_id as
    # still in progress and resume it instead of hitting this test's
    # persisted-row 409 path.
    async with action_run_store._lock:
        action_run_store._runs.pop(body["run_id"], None)

    db.add(ActionRun(
        user_id=test_user["user"].id,
        scenario_id=body["scenario_id"],
        daily_challenge_id=body["daily_challenge_id"],
        seed=body["seed"],
        mode="daily",
        action_log=[],
        score_breakdown={},
        total_score=100,
        duration_seconds=60,
        outcome="win",
    ))
    await db.flush()

    second = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    assert second.status_code == 409


async def test_daily_action_run_double_post_resumes_the_live_run_instead_of_conflicting(client, db, test_user, approved_scenario):
    """QA fix: the 409 pre-check above only queries persisted `ActionRun`
    rows, but a row exists only once `finalize()` commits it — a run still
    in progress lives solely in `action_run_store`. Before this fix, a
    double-tap/refresh sailed past that pre-check and started a SECOND
    live run for the same (user, challenge); that second run's own
    finalize() would then crash on `uq_action_run_daily_challenge_user`,
    losing the player's run.end. Confirms end-to-end: the second POST
    resumes the SAME run_id with 200 + resumed=True (never a second 201,
    never a 409), exactly one live run exists in the store the whole time,
    and finalizing it once succeeds cleanly — there is no second live run
    left over to attempt a colliding finalize against."""
    from sqlalchemy import select
    from app.models.action_run import ActionRun

    first = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["resumed"] is False

    second = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["resumed"] is True
    assert second_body["run_id"] == first_body["run_id"]
    assert second_body["daily_challenge_id"] == first_body["daily_challenge_id"]
    assert second_body["scenario_id"] == first_body["scenario_id"]
    assert second_body["seed"] == first_body["seed"]

    live_runs_for_challenge = [
        live for live in action_run_store._runs.values()
        if live.user_id == test_user["user"].id
        and live.daily_challenge_id == first_body["daily_challenge_id"]
    ]
    assert len(live_runs_for_challenge) == 1  # the double-POST did not spawn a sibling live run

    # Finalizing the one live run succeeds cleanly — there was never a
    # second live run to attempt a colliding finalize with (the second
    # finalize this bug used to cause never happens).
    summary = await action_run_store.finalize(db, first_body["run_id"])
    assert summary is not None
    assert await action_run_store.get(first_body["run_id"]) is None

    result = await db.execute(
        select(ActionRun).where(ActionRun.daily_challenge_id == first_body["daily_challenge_id"])
    )
    assert len(result.scalars().all()) == 1  # exactly one ActionRun row — no constraint collision

    # A genuinely-finished run now correctly 409s on a further attempt,
    # via the persisted-row pre-check — unaffected by this fix.
    third = await client.post("/api/v1/daily/action-run", headers=_auth_headers(test_user["token"]))
    assert third.status_code == 409


# ── Mid-loop 8-minute cap enforcement (WS handler layer) ────────────────────────

async def test_daily_mode_cap_force_ends_the_run_mid_loop_not_via_final_stage():
    """The daily cap (480s) must fire on its own, mid-loop, inside a
    single WS session — not only via action_run_store's separate
    abandonment sweep (already covered by test_action_run_store.py).
    _SLOW_DECISION_TREE's gate triggers at 900s, so a run that ends at
    ~495s can only have ended via the CAP condition."""
    from tests.conftest import ensure_test_user_row

    await ensure_test_user_row("daily-cap-owner-1")
    scenario = await _make_scenario()
    challenge = await _make_daily_challenge(scenario.id, date(2030, 2, 1))

    compiled = action_engine.compile_scenario(scenario, seed=1)
    run_id = str(uuid.uuid4())
    await action_run_store.start_run(
        run_id, "daily-cap-owner-1", scenario.id, "daily", compiled,
        daily_challenge_id=challenge.id,
    )

    final_stage = next(s for s in compiled.stages if s.is_final)
    assert final_stage.trigger_seconds >= 900  # sanity: this test needs the CAP, not the final stage, to fire

    # 11 * 45s (scan_network) = 495s >= 480s cap; 495s < 900s final-stage trigger.
    ws = FakeWebSocket(incoming=['{"type": "action.submit", "verb": "scan_network"}'] * 11)
    await action_run_ws_handler(ws, run_id, "daily-cap-owner-1")

    run_end_events = [m for m in ws.sent if m["type"] == "run.end"]
    assert len(run_end_events) == 1
    assert run_end_events[0]["daily_challenge_id"] == challenge.id
    # Final stage never fired — determine_outcome treats an unfired final
    # stage as a win, regardless of the cap having ended the run.
    assert run_end_events[0]["outcome"] == "win"

    tick_events = [m for m in ws.sent if m["type"] == "clock.tick"]
    assert tick_events[-1]["elapsed_seconds"] == 495
    assert tick_events[-1]["elapsed_seconds"] >= 480  # the cap that ended it

    assert await action_run_store.get(run_id) is None


# ── run.end broadcast carry-over ─────────────────────────────────────────────────

async def test_daily_run_end_carries_over_streak_and_rank_fields():
    from tests.conftest import ensure_test_user_row

    await ensure_test_user_row("daily-carryover-owner-1")
    scenario = await _make_scenario()
    challenge = await _make_daily_challenge(scenario.id, date(2030, 2, 2))

    compiled = action_engine.compile_scenario(scenario, seed=1)
    run_id = str(uuid.uuid4())
    await action_run_store.start_run(
        run_id, "daily-carryover-owner-1", scenario.id, "daily", compiled,
        daily_challenge_id=challenge.id,
    )

    ws = FakeWebSocket(incoming=['{"type": "action.submit", "verb": "scan_network"}'] * 11)
    await action_run_ws_handler(ws, run_id, "daily-carryover-owner-1")

    run_end_events = [m for m in ws.sent if m["type"] == "run.end"]
    assert len(run_end_events) == 1
    summary = run_end_events[0]

    assert summary["daily_challenge_id"] == challenge.id
    assert summary["challenge_number"] == challenge.challenge_number
    assert summary["rank"] == 1  # only run on this challenge
    assert summary["current_streak"] == 1
    assert summary["longest_streak"] == 1
    assert summary["total_dailies_played"] == 1
    assert summary["total_attempts_today"] == 1
    assert summary["avg_score_today"] == summary["score_breakdown"]["total_score"]

    # Persisted side effects, independent of the run.end payload.
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select
    from app.models.daily_challenge import DailyChallenge, UserStreak

    async with AsyncSessionLocal() as db:
        refreshed_challenge = (await db.execute(
            select(DailyChallenge).where(DailyChallenge.id == challenge.id)
        )).scalar_one()
        streak = (await db.execute(
            select(UserStreak).where(UserStreak.user_id == "daily-carryover-owner-1")
        )).scalar_one()

    assert refreshed_challenge.total_attempts == 1
    assert streak.current_streak == 1

    assert await action_run_store.get(run_id) is None


# ── Sweep abandonment carry-over (main.py's _run_action_run_sweep_iteration) ────
#
# QA fix: action_run_store.sweep_expired() used to force-finalize an
# abandoned run and then discard finalize()'s summary entirely — a
# connected-but-slow player whose run the sweep force-finalized was left
# with a dead socket instead of their debrief, and (for mode="daily") lost
# streak/rank credit outright since record_daily_action_run_result was
# never reached on this path. These exercise the REAL production wiring
# (main._run_action_run_sweep_iteration -> action_run_store.sweep_expired
# -> manager.broadcast), not a reimplementation of it.

async def test_swept_daily_run_broadcasts_run_end_and_carries_over_streak():
    from datetime import datetime, timedelta

    from app.main import _run_action_run_sweep_iteration
    from app.services.action_run_store import CAP_SECONDS_BY_MODE, SWEEP_GRACE_SECONDS
    from app.websocket.manager import manager
    from tests.conftest import ensure_test_user_row

    await ensure_test_user_row("daily-sweep-owner-1")
    scenario = await _make_scenario()
    challenge = await _make_daily_challenge(scenario.id, date(2030, 2, 5))

    compiled = action_engine.compile_scenario(scenario, seed=1)
    run_id = str(uuid.uuid4())
    live = await action_run_store.start_run(
        run_id, "daily-sweep-owner-1", scenario.id, "daily", compiled,
        daily_challenge_id=challenge.id,
    )
    # Backdate real_started_at past cap+grace — simulating an abandoned tab
    # whose socket, per this test, is STILL connected (a slow/backgrounded
    # client, not a closed one) — exercises the sweep's own time math
    # directly, same convention as test_action_run_store.py's sweep tests.
    overdue = CAP_SECONDS_BY_MODE["daily"] + SWEEP_GRACE_SECONDS + 5
    live.real_started_at = datetime.utcnow() - timedelta(seconds=overdue)

    ws = FakeWebSocket()
    await manager.connect(run_id, ws)
    try:
        await _run_action_run_sweep_iteration()

        run_end_events = [m for m in ws.sent if m["type"] == "run.end"]
        assert len(run_end_events) == 1
        summary = run_end_events[0]
        assert summary["outcome"] == "loss"  # forced, not the natural determine_outcome
        assert summary["daily_challenge_id"] == challenge.id
        assert summary["challenge_number"] == challenge.challenge_number
        assert summary["rank"] == 1  # only run on this challenge
        assert summary["current_streak"] == 1
        assert summary["longest_streak"] == 1
        assert summary["total_dailies_played"] == 1

        assert await action_run_store.get(run_id) is None

        from app.db.session import AsyncSessionLocal
        from sqlalchemy import select
        from app.models.action_run import ActionRun
        from app.models.daily_challenge import DailyChallenge, UserStreak

        async with AsyncSessionLocal() as db:
            refreshed_challenge = (await db.execute(
                select(DailyChallenge).where(DailyChallenge.id == challenge.id)
            )).scalar_one()
            streak = (await db.execute(
                select(UserStreak).where(UserStreak.user_id == "daily-sweep-owner-1")
            )).scalar_one()
            action_run = (await db.execute(
                select(ActionRun).where(ActionRun.daily_challenge_id == challenge.id)
            )).scalar_one()

        assert refreshed_challenge.total_attempts == 1
        assert streak.current_streak == 1
        assert action_run.outcome == "loss"
    finally:
        manager.disconnect(run_id, ws)


async def test_swept_non_daily_run_also_broadcasts_run_end_to_a_live_socket():
    """Same fix, non-daily mode: the broadcast itself must not depend on
    sweep_expired's daily-routing branch — a scenario-mode run's swept
    debrief must reach a connected socket too, with no daily fields
    leaking in when there's no daily_challenge_id to carry over."""
    from datetime import datetime, timedelta

    from app.main import _run_action_run_sweep_iteration
    from app.services.action_run_store import CAP_SECONDS_BY_MODE, SWEEP_GRACE_SECONDS
    from app.websocket.manager import manager
    from tests.conftest import ensure_test_user_row

    await ensure_test_user_row("scenario-sweep-owner-1")
    scenario = await _make_scenario()

    compiled = action_engine.compile_scenario(scenario, seed=1)
    run_id = str(uuid.uuid4())
    live = await action_run_store.start_run(
        run_id, "scenario-sweep-owner-1", scenario.id, "scenario", compiled,
    )
    overdue = CAP_SECONDS_BY_MODE["scenario"] + SWEEP_GRACE_SECONDS + 5
    live.real_started_at = datetime.utcnow() - timedelta(seconds=overdue)

    ws = FakeWebSocket()
    await manager.connect(run_id, ws)
    try:
        await _run_action_run_sweep_iteration()

        run_end_events = [m for m in ws.sent if m["type"] == "run.end"]
        assert len(run_end_events) == 1
        assert run_end_events[0]["outcome"] == "loss"
        assert "daily_challenge_id" not in run_end_events[0]

        assert await action_run_store.get(run_id) is None
    finally:
        manager.disconnect(run_id, ws)


# ── Rank ordering (focused unit test on record_daily_action_run_result) ─────────

async def test_record_daily_action_run_result_ranks_by_total_score_descending():
    from app.db.session import AsyncSessionLocal
    from app.models.action_run import ActionRun
    from tests.conftest import ensure_test_user_row

    await ensure_test_user_row("daily-rank-a")
    await ensure_test_user_row("daily-rank-b")
    scenario = await _make_scenario()
    challenge = await _make_daily_challenge(scenario.id, date(2030, 2, 3))

    async with AsyncSessionLocal() as db:
        db.add(ActionRun(
            user_id="daily-rank-a", scenario_id=scenario.id, daily_challenge_id=challenge.id,
            seed=1, mode="daily", action_log=[], score_breakdown={}, total_score=500,
            duration_seconds=200, outcome="win",
        ))
        db.add(ActionRun(
            user_id="daily-rank-b", scenario_id=scenario.id, daily_challenge_id=challenge.id,
            seed=1, mode="daily", action_log=[], score_breakdown={}, total_score=200,
            duration_seconds=300, outcome="partial",
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        summary_a = await record_daily_action_run_result(db, challenge.id, "daily-rank-a", 500)
    async with AsyncSessionLocal() as db:
        summary_b = await record_daily_action_run_result(db, challenge.id, "daily-rank-b", 200)

    assert summary_a["rank"] == 1
    assert summary_b["rank"] == 2


# ── GET /daily/action-leaderboard/{id} ───────────────────────────────────────────

async def test_action_leaderboard_orders_by_total_score(client, db, test_user, admin_user, approved_scenario):
    from app.models.action_run import ActionRun
    from app.models.daily_challenge import DailyChallenge

    challenge = DailyChallenge(
        id=str(uuid.uuid4()), scenario_id=approved_scenario.id,
        challenge_date=date(2030, 2, 4), challenge_number=1,
    )
    db.add(challenge)
    await db.flush()

    db.add(ActionRun(
        user_id=test_user["user"].id, scenario_id=approved_scenario.id, daily_challenge_id=challenge.id,
        seed=1, mode="daily", action_log=[], score_breakdown={}, total_score=300,
        duration_seconds=200, outcome="win",
    ))
    db.add(ActionRun(
        user_id=admin_user["user"].id, scenario_id=approved_scenario.id, daily_challenge_id=challenge.id,
        seed=1, mode="daily", action_log=[], score_breakdown={}, total_score=700,
        duration_seconds=200, outcome="win",
    ))
    await db.flush()

    resp = await client.get(
        f"/api/v1/daily/action-leaderboard/{challenge.id}",
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    assert entries[0]["total_score"] == 700
    assert entries[0]["rank"] == 1
    assert entries[1]["total_score"] == 300
    assert entries[1]["rank"] == 2
