"""Ghost race beat detection — finalize-time recording and race context."""
import uuid
from dataclasses import replace
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.action_run import ActionRun
from app.models.daily_challenge import DailyChallenge
from app.models.ghost_race_beat import GhostRaceBeat
from app.models.user import User
from app.services import action_engine
from app.services.action_run_store import ActionRunStore, action_run_store

pytestmark = pytest.mark.asyncio

_FAST_DECISION_TREE = [
    {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
     "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
]


@pytest.fixture
async def fast_scenario(db):
    from app.models.scenario import Scenario

    scenario = Scenario(
        title="Beat Test Scenario",
        source_type="manual",
        source_reference="TEST-BEAT-001",
        difficulty="practitioner",
        industry_vertical="energy",
        status="approved",
        decision_tree=_FAST_DECISION_TREE,
        compression_ratio=1.0,
        alert_sequence=[],
    )
    db.add(scenario)
    await db.flush()
    return scenario


@pytest.fixture
def store():
    return ActionRunStore()


@pytest.fixture
async def ghost_owner(db, test_org):
    user = User(
        email=f"ghost-owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Ghost Owner",
        role="analyst",
        organization_id=test_org.id,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def racer_user(db, test_org):
    user = User(
        email=f"racer-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Racer",
        role="analyst",
        organization_id=test_org.id,
    )
    db.add(user)
    await db.flush()
    token = create_access_token({"sub": user.id})
    return {"user": user, "token": token}


async def _insert_ghost(
    db,
    *,
    owner_id: str,
    scenario_id: str,
    mode: str = "scenario",
    duration_seconds: int = 200,
    outcome: str = "contained",
    seed: int = 424242,
    share_token: str | None = None,
    daily_challenge_id: str | None = None,
) -> ActionRun:
    run = ActionRun(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        scenario_id=scenario_id,
        daily_challenge_id=daily_challenge_id,
        seed=seed,
        mode=mode,
        action_log=[],
        score_breakdown={"total_score": 500},
        total_score=500,
        duration_seconds=duration_seconds,
        outcome=outcome,
        share_token=share_token,
        public_snapshot={"hosts": [], "edges": [], "techniques_encountered": []},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _finalize_race(
    store: ActionRunStore,
    db,
    *,
    scenario,
    racer_user_id: str,
    ghost: ActionRun,
    racer_seconds: int,
    outcome: str,
):
    compiled = action_engine.compile_scenario(scenario, seed=ghost.seed)
    run_id = str(uuid.uuid4())
    await store.start_run(
        run_id,
        racer_user_id,
        scenario.id,
        "scenario",
        compiled,
        ghost_opponent_run_id=ghost.id,
    )
    live = await store.get(run_id)
    live.run_state = replace(live.run_state, elapsed_seconds=racer_seconds)
    with patch("app.services.action_run_store.verb_engine.determine_outcome", return_value=outcome):
        return await store.finalize(db, run_id)


async def _beats_for_racer(db, racer_user_id: str) -> list[GhostRaceBeat]:
    result = await db.execute(
        select(GhostRaceBeat).where(GhostRaceBeat.racer_user_id == racer_user_id)
    )
    return list(result.scalars().all())


async def test_finalize_records_beat_when_faster_and_contained(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    ghost = await _insert_ghost(
        db, owner_id=ghost_owner.id, scenario_id=fast_scenario.id, duration_seconds=200,
    )
    summary = await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user_id=racer_user["user"].id,
        ghost=ghost,
        racer_seconds=150,
        outcome="contained",
    )
    assert summary is not None

    beats = await _beats_for_racer(db, racer_user["user"].id)
    assert len(beats) == 1
    beat = beats[0]
    assert beat.racer_user_id == racer_user["user"].id
    assert beat.ghost_action_run_id == ghost.id
    assert beat.ghost_owner_user_id == ghost_owner.id
    assert beat.racer_action_run_id == summary["action_run_id"]
    assert beat.racer_containment_seconds == 150
    assert beat.ghost_containment_seconds == 200
    assert beat.ghost_owner_beat_notifications_enabled is True
    assert beat.beat_at is not None
    assert summary["ghost_race_beat"] is True
    assert summary["response_index_bump"] == 15
    assert summary["response_index"] == 1215


async def test_finalize_no_beat_when_slower(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    ghost = await _insert_ghost(
        db, owner_id=ghost_owner.id, scenario_id=fast_scenario.id, duration_seconds=100,
    )
    await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user_id=racer_user["user"].id,
        ghost=ghost,
        racer_seconds=150,
        outcome="contained",
    )
    assert await _beats_for_racer(db, racer_user["user"].id) == []


async def test_finalize_no_beat_when_not_contained(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    ghost = await _insert_ghost(
        db, owner_id=ghost_owner.id, scenario_id=fast_scenario.id, duration_seconds=300,
    )
    await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user_id=racer_user["user"].id,
        ghost=ghost,
        racer_seconds=50,
        outcome="breached",
    )
    assert await _beats_for_racer(db, racer_user["user"].id) == []


async def test_finalize_beat_against_daily_mode_ghost(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    challenge = DailyChallenge(
        id=str(uuid.uuid4()),
        scenario_id=fast_scenario.id,
        challenge_date=date(2031, 6, 1),
        challenge_number=9001,
        is_active=True,
        total_attempts=0,
    )
    db.add(challenge)
    await db.flush()
    ghost = await _insert_ghost(
        db,
        owner_id=ghost_owner.id,
        scenario_id=fast_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        duration_seconds=180,
        seed=999,
    )
    await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user_id=racer_user["user"].id,
        ghost=ghost,
        racer_seconds=120,
        outcome="contained_at_cost",
    )
    beats = await _beats_for_racer(db, racer_user["user"].id)
    assert len(beats) == 1
    assert beats[0].ghost_action_run_id == ghost.id
    assert beats[0].ghost_containment_seconds == 180


async def test_finalize_beat_against_scenario_mode_ghost(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    ghost = await _insert_ghost(
        db,
        owner_id=ghost_owner.id,
        scenario_id=fast_scenario.id,
        mode="scenario",
        duration_seconds=250,
        share_token=f"tok{uuid.uuid4().hex[:12]}",
    )
    await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user_id=racer_user["user"].id,
        ghost=ghost,
        racer_seconds=100,
        outcome="contained",
    )
    beats = await _beats_for_racer(db, racer_user["user"].id)
    assert len(beats) == 1
    assert beats[0].ghost_action_run_id == ghost.id


async def test_beat_still_recorded_when_owner_notifications_disabled(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    ghost_owner.beat_notifications_enabled = False
    await db.commit()
    ghost = await _insert_ghost(
        db, owner_id=ghost_owner.id, scenario_id=fast_scenario.id, duration_seconds=200,
    )
    await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user_id=racer_user["user"].id,
        ghost=ghost,
        racer_seconds=100,
        outcome="contained",
    )
    beats = await _beats_for_racer(db, racer_user["user"].id)
    assert len(beats) == 1
    assert beats[0].ghost_owner_beat_notifications_enabled is False


async def test_http_start_race_stashes_ghost_opponent_run_id(
    client, db, test_user, approved_scenario, ghost_owner,
):
    token = f"raceBeat{uuid.uuid4().hex[:10]}"
    ghost = await _insert_ghost(
        db,
        owner_id=ghost_owner.id,
        scenario_id=approved_scenario.id,
        share_token=token,
        seed=12345,
    )
    resp = await client.post(
        "/api/v1/action-runs/race",
        json={"share_token": token},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["run_id"]
    live = await action_run_store.get(run_id)
    assert live is not None
    assert live.ghost_opponent_run_id == ghost.id
    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)
