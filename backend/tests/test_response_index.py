"""Per-user Response Index — ghost-race beat bumps."""
import uuid
from dataclasses import replace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.action_run import ActionRun
from app.models.user import User
from app.services import action_engine
from app.services.action_run_store import ActionRunStore
from app.services.response_index_service import (
    RESPONSE_INDEX_BEAT_BUMP,
    RESPONSE_INDEX_DEFAULT,
)

pytestmark = pytest.mark.asyncio

_FAST_DECISION_TREE = [
    {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
     "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def fast_scenario(db):
    from app.models.scenario import Scenario

    scenario = Scenario(
        title="Response Index Scenario",
        source_type="manual",
        source_reference="TEST-RI-001",
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


async def _insert_ghost(db, owner_id: str, scenario_id: str, duration_seconds: int = 200) -> ActionRun:
    run = ActionRun(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        scenario_id=scenario_id,
        seed=424242,
        mode="scenario",
        action_log=[],
        score_breakdown={"total_score": 500},
        total_score=500,
        duration_seconds=duration_seconds,
        outcome="contained",
        public_snapshot={"hosts": [], "edges": [], "techniques_encountered": []},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _finalize_race(store, db, *, scenario, racer_user, ghost, racer_seconds: int, outcome: str):
    run_id = str(uuid.uuid4())
    compiled = action_engine.compile_scenario(scenario, seed=ghost.seed)
    await store.start_run(
        run_id,
        racer_user.id,
        scenario.id,
        "scenario",
        compiled,
        ghost_opponent_run_id=ghost.id,
    )
    live = await store.get(run_id)
    live.run_state = replace(live.run_state, elapsed_seconds=racer_seconds)
    with patch("app.services.action_run_store.verb_engine.determine_outcome", return_value=outcome):
        return await store.finalize(db, run_id)


async def test_ghost_race_beat_bumps_response_index(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    racer = racer_user["user"]
    assert racer.response_index == RESPONSE_INDEX_DEFAULT

    ghost = await _insert_ghost(db, ghost_owner.id, fast_scenario.id, duration_seconds=200)
    summary = await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user=racer,
        ghost=ghost,
        racer_seconds=150,
        outcome="contained",
    )

    assert summary["ghost_race_beat"] is True
    assert summary["response_index_bump"] == RESPONSE_INDEX_BEAT_BUMP
    assert summary["response_index"] == RESPONSE_INDEX_DEFAULT + RESPONSE_INDEX_BEAT_BUMP

    refreshed = await db.scalar(select(User).where(User.id == racer.id))
    assert refreshed.response_index == RESPONSE_INDEX_DEFAULT + RESPONSE_INDEX_BEAT_BUMP
    assert refreshed.arena_rating == 1200


async def test_non_beat_does_not_bump_response_index(
    db, store, fast_scenario, ghost_owner, racer_user,
):
    racer = racer_user["user"]
    ghost = await _insert_ghost(db, ghost_owner.id, fast_scenario.id, duration_seconds=100)
    summary = await _finalize_race(
        store, db,
        scenario=fast_scenario,
        racer_user=racer,
        ghost=ghost,
        racer_seconds=150,
        outcome="contained",
    )

    assert "ghost_race_beat" not in summary
    assert "response_index_bump" not in summary

    refreshed = await db.scalar(select(User).where(User.id == racer.id))
    assert refreshed.response_index == RESPONSE_INDEX_DEFAULT


async def test_profile_me_includes_response_index(client, db, test_user):
    test_user["user"].response_index = 1275
    await db.flush()

    resp = await client.get("/api/v1/profile/me", headers=_auth_headers(test_user["token"]))
    assert resp.status_code == 200
    assert resp.json()["response_index"] == 1275
