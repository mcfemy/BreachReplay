"""
HTTP-level tests for the Phase 2.5 CMMC Evidence Layer's EvidenceSession
designation flow (build-order item 3): backend/app/api/routes/cmmc.py's
item-3 routes and app/services/cmmc_evidence.py's designation/aggregation
logic.

Split out from test_cmmc_isolation.py (item 1) and test_cmmc_invitations.py
(item 2), same reasoning as before — these exercise the full route stack.

The non-negotiable ones, per Femi's explicit constraints for this item:
- consultant_admin isolation (A can't touch B's client orgs/sessions/runs);
- a client_participant has NO route into any of this, not even read-only
  ones — the direct enforcement of "compliance is an export, never an
  experience";
- designating an already-designated run, a wrong-scenario run, or a
  wrong-client-org run are all rejected, all-or-nothing, never silently
  partial;
- the aggregate view never flattens multiple participants' outcomes into
  a single value — outcome_distribution is a histogram, never a scalar.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def _user(email: str, *, role: str = "analyst") -> User:
    return User(
        email=email,
        hashed_password=hash_password("StrongPass1!"),
        full_name=email,
        role=role,
        organization_id=None,
    )


async def _make_consultant_admin(db) -> tuple[User, str, ConsultingOrg]:
    org = ConsultingOrg(name=f"RPO {uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    user = _user(_unique_email("consultant"))
    db.add(user)
    await db.flush()
    db.add(Membership(user_id=user.id, consulting_org_id=org.id, role="consultant_admin"))
    await db.flush()
    token = create_access_token({"sub": user.id})
    return user, token, org


async def _make_client_org(db, consulting_org: ConsultingOrg) -> ClientOrg:
    client_org = ClientOrg(consulting_org_id=consulting_org.id, name=f"Client {uuid.uuid4().hex[:6]}")
    db.add(client_org)
    await db.flush()
    return client_org


async def _make_participant(db, client_org: ClientOrg) -> tuple[User, str]:
    user = _user(_unique_email("participant"))
    db.add(user)
    await db.flush()
    db.add(Membership(user_id=user.id, client_org_id=client_org.id, role="client_participant"))
    await db.flush()
    token = create_access_token({"sub": user.id})
    return user, token


def _score_breakdown(outcome: str, total_score: int, *, collateral=None, collateral_penalty: int = 0) -> dict:
    return {
        "outcome": outcome,
        "outcome_base": 0,
        "evidence_points": 0,
        "evidence_found": 1,
        "evidence_total": 2,
        "speed_bonus": 0,
        "penalty_total": 0,
        "penalties": [],
        "collateral": collateral or [],
        "collateral_penalty": collateral_penalty,
        "total_score": total_score,
        "score_pct": 50.0,
    }


async def _make_action_run(
    db, user: User, scenario, *,
    outcome: str = "contained", total_score: int = 100, duration_seconds: int = 300,
    created_at: datetime | None = None, action_log: list | None = None,
    collateral=None, collateral_penalty: int = 0, evidence_session_id: str | None = None,
) -> ActionRun:
    run = ActionRun(
        user_id=user.id,
        scenario_id=scenario.id,
        seed=1,
        mode="scenario",
        action_log=action_log or [],
        score_breakdown=_score_breakdown(outcome, total_score, collateral=collateral, collateral_penalty=collateral_penalty),
        total_score=total_score,
        duration_seconds=duration_seconds,
        outcome=outcome,
        created_at=created_at or datetime.utcnow(),
        evidence_session_id=evidence_session_id,
    )
    db.add(run)
    await db.flush()
    return run


# ── consultant isolation ─────────────────────────────────────────────────

async def test_consultant_b_cannot_list_consultant_a_client_org_runs(client, db):
    _, token_a, org_a = await _make_consultant_admin(db)
    _, token_b, _ = await _make_consultant_admin(db)
    client_org_a = await _make_client_org(db, org_a)

    resp = await client.get(f"/api/v1/cmmc/client-orgs/{client_org_a.id}/runs", headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_consultant_admin_lists_client_org_runs(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, _ = await _make_participant(db, client_org)
    run = await _make_action_run(db, participant, approved_scenario)
    await db.commit()

    resp = await client.get(f"/api/v1/cmmc/client-orgs/{client_org.id}/runs", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == run.id
    assert body[0]["participant_name"] == participant.full_name


async def test_consultant_b_cannot_view_or_designate_into_consultant_a_evidence_session(client, db, approved_scenario):
    _, token_a, org_a = await _make_consultant_admin(db)
    _, token_b, _ = await _make_consultant_admin(db)
    client_org_a = await _make_client_org(db, org_a)
    session = EvidenceSession(
        client_org_id=client_org_a.id, title="A's session",
        scenario_id=approved_scenario.id, exercise_date=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()

    b_headers = auth_headers(token_b)
    assert (await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}", headers=b_headers)).status_code == 404
    assert (await client.patch(f"/api/v1/cmmc/evidence-sessions/{session.id}", json={"title": "stolen"}, headers=b_headers)).status_code == 404
    assert (await client.post(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": ["x"]}, headers=b_headers)).status_code == 404
    assert (await client.delete(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs/x", headers=b_headers)).status_code == 404
    assert (await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}/aggregate", headers=b_headers)).status_code == 404


# ── "compliance is an export, never an experience": no participant route ──

async def test_client_participant_has_no_route_into_evidence_sessions(client, db, approved_scenario):
    _, _, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, participant_token = await _make_participant(db, client_org)
    session = EvidenceSession(
        client_org_id=client_org.id, title="Session",
        scenario_id=approved_scenario.id, exercise_date=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()

    headers = auth_headers(participant_token)
    assert (await client.get(f"/api/v1/cmmc/client-orgs/{client_org.id}/runs", headers=headers)).status_code == 404
    assert (await client.post(
        f"/api/v1/cmmc/client-orgs/{client_org.id}/evidence-sessions",
        json={"title": "x", "scenario_id": approved_scenario.id, "exercise_date": "2026-01-01T00:00:00"},
        headers=headers,
    )).status_code == 404
    assert (await client.get(f"/api/v1/cmmc/client-orgs/{client_org.id}/evidence-sessions", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}", headers=headers)).status_code == 404
    assert (await client.patch(f"/api/v1/cmmc/evidence-sessions/{session.id}", json={"title": "x"}, headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": ["x"]}, headers=headers)).status_code == 404
    assert (await client.delete(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs/x", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}/aggregate", headers=headers)).status_code == 404


# ── create / list / view / update ────────────────────────────────────────

async def test_create_and_list_and_view_evidence_session(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)

    create_resp = await client.post(
        f"/api/v1/cmmc/client-orgs/{client_org.id}/evidence-sessions",
        json={"title": "Q3 Tabletop", "scenario_id": approved_scenario.id, "exercise_date": "2026-07-01T00:00:00"},
        headers=auth_headers(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    session_id = create_resp.json()["id"]

    list_resp = await client.get(f"/api/v1/cmmc/client-orgs/{client_org.id}/evidence-sessions", headers=auth_headers(token))
    assert list_resp.status_code == 200
    assert any(s["id"] == session_id for s in list_resp.json())

    view_resp = await client.get(f"/api/v1/cmmc/evidence-sessions/{session_id}", headers=auth_headers(token))
    assert view_resp.status_code == 200
    assert view_resp.json()["title"] == "Q3 Tabletop"
    assert view_resp.json()["runs"] == []

    patch_resp = await client.patch(
        f"/api/v1/cmmc/evidence-sessions/{session_id}", json={"title": "Q3 Tabletop — Revised"}, headers=auth_headers(token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Q3 Tabletop — Revised"


# ── designation validation ───────────────────────────────────────────────

async def test_designate_already_designated_run_to_different_session_rejected(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, _ = await _make_participant(db, client_org)

    session1 = EvidenceSession(client_org_id=client_org.id, title="S1", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    session2 = EvidenceSession(client_org_id=client_org.id, title="S2", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add_all([session1, session2])
    await db.flush()
    run = await _make_action_run(db, participant, approved_scenario, evidence_session_id=session1.id)
    await db.commit()

    resp = await client.post(
        f"/api/v1/cmmc/evidence-sessions/{session2.id}/runs", json={"run_ids": [run.id]}, headers=auth_headers(token),
    )
    assert resp.status_code == 409

    await db.refresh(run)
    assert run.evidence_session_id == session1.id


async def test_designate_run_wrong_scenario_rejected(client, db, approved_scenario):
    from app.models.scenario import Scenario

    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, _ = await _make_participant(db, client_org)

    other_scenario = Scenario(
        title="Other Scenario", source_type="manual", source_reference="TEST-002",
        difficulty="practitioner", status="approved", decision_tree=approved_scenario.decision_tree,
        compression_ratio=1.0, alert_sequence=approved_scenario.alert_sequence,
    )
    db.add(other_scenario)
    await db.flush()

    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()
    run = await _make_action_run(db, participant, other_scenario)
    await db.commit()

    resp = await client.post(
        f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": [run.id]}, headers=auth_headers(token),
    )
    assert resp.status_code == 409
    await db.refresh(run)
    assert run.evidence_session_id is None


async def test_designate_run_wrong_client_org_rejected(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org_a = await _make_client_org(db, org)
    client_org_b = await _make_client_org(db, org)
    outsider, _ = await _make_participant(db, client_org_b)

    session = EvidenceSession(client_org_id=client_org_a.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()
    run = await _make_action_run(db, outsider, approved_scenario)
    await db.commit()

    resp = await client.post(
        f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": [run.id]}, headers=auth_headers(token),
    )
    assert resp.status_code == 409
    await db.refresh(run)
    assert run.evidence_session_id is None


async def test_designate_is_idempotent_for_same_session(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, _ = await _make_participant(db, client_org)
    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()
    run = await _make_action_run(db, participant, approved_scenario)
    await db.commit()

    first = await client.post(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": [run.id]}, headers=auth_headers(token))
    assert first.status_code == 200
    second = await client.post(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": [run.id]}, headers=auth_headers(token))
    assert second.status_code == 200


async def test_remove_run_from_evidence_session(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, _ = await _make_participant(db, client_org)
    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()
    run = await _make_action_run(db, participant, approved_scenario, evidence_session_id=session.id)
    await db.commit()

    resp = await client.delete(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs/{run.id}", headers=auth_headers(token))
    assert resp.status_code == 200
    await db.refresh(run)
    assert run.evidence_session_id is None


async def test_finalized_session_blocks_add_and_remove_runs(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    participant, _ = await _make_participant(db, client_org)
    session = EvidenceSession(
        client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow(),
        consultant_signoff={"signed_by": "someone", "signed_at": "2026-01-01T00:00:00"},
    )
    db.add(session)
    await db.flush()
    run = await _make_action_run(db, participant, approved_scenario)
    await db.commit()

    add_resp = await client.post(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs", json={"run_ids": [run.id]}, headers=auth_headers(token))
    assert add_resp.status_code == 400

    remove_resp = await client.delete(f"/api/v1/cmmc/evidence-sessions/{session.id}/runs/{run.id}", headers=auth_headers(token))
    assert remove_resp.status_code == 400


# ── aggregation ───────────────────────────────────────────────────────────

async def test_aggregate_outcome_distribution_never_averages(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()

    for outcome in ("contained", "overreacted", "breached"):
        participant, _ = await _make_participant(db, client_org)
        await _make_action_run(db, participant, approved_scenario, outcome=outcome, evidence_session_id=session.id)
    await db.commit()

    resp = await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}/aggregate", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "outcome" not in body
    assert body["outcome_distribution"] == {
        "contained": 1, "contained_at_cost": 0, "overreacted": 1,
        "breached_spread_limited": 0, "breached": 1,
    }
    assert body["participant_count"] == 3
    assert {p["outcome"] for p in body["participants"]} == {"contained", "overreacted", "breached"}


async def test_aggregate_timeline_merges_chronologically_with_participant_attribution(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()

    t0 = datetime(2026, 1, 1, 12, 0, 0)

    p1, _ = await _make_participant(db, client_org)
    run1 = await _make_action_run(
        db, p1, approved_scenario,
        created_at=t0 + timedelta(seconds=1000), duration_seconds=600,
        action_log=[{"sequence_number": 1, "verb": "scan", "target": "h1", "elapsed_seconds": 100, "cost": 10}],
        evidence_session_id=session.id,
    )
    # run1's entry estimated_timestamp = t0 + 1000 - 600 + 100 = t0 + 500

    p2, _ = await _make_participant(db, client_org)
    run2 = await _make_action_run(
        db, p2, approved_scenario,
        created_at=t0 + timedelta(seconds=500), duration_seconds=300,
        action_log=[{"sequence_number": 1, "verb": "isolate", "target": "h2", "elapsed_seconds": 50, "cost": 10}],
        evidence_session_id=session.id,
    )
    # run2's entry estimated_timestamp = t0 + 500 - 300 + 50 = t0 + 250 (earlier than run1's)
    await db.commit()

    resp = await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}/aggregate", headers=auth_headers(token))
    assert resp.status_code == 200
    timeline = resp.json()["timeline"]
    assert len(timeline) == 2
    assert timeline[0]["participant_user_id"] == p2.id
    assert timeline[0]["verb"] == "isolate"
    assert timeline[1]["participant_user_id"] == p1.id
    assert timeline[1]["verb"] == "scan"
    assert timeline[0]["estimated_timestamp"] < timeline[1]["estimated_timestamp"]


async def test_aggregate_collateral_reported_per_participant_and_as_total(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()

    p1, _ = await _make_participant(db, client_org)
    await _make_action_run(
        db, p1, approved_scenario, outcome="contained_at_cost",
        collateral=[{"host_id": "h1", "hostname": "host-1", "weight": 5}], collateral_penalty=5,
        evidence_session_id=session.id,
    )
    p2, _ = await _make_participant(db, client_org)
    await _make_action_run(
        db, p2, approved_scenario, outcome="overreacted",
        collateral=[{"host_id": "h2", "hostname": "host-2", "weight": 8}], collateral_penalty=8,
        evidence_session_id=session.id,
    )
    await db.commit()

    resp = await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}/aggregate", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["collateral_total_penalty"] == 13
    penalties = {p["collateral_penalty"] for p in body["participants"]}
    assert penalties == {5, 8}


async def test_aggregate_escalations_pooled_across_participants(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = EvidenceSession(client_org_id=client_org.id, title="S", scenario_id=approved_scenario.id, exercise_date=datetime.utcnow())
    db.add(session)
    await db.flush()

    p1, _ = await _make_participant(db, client_org)
    await _make_action_run(
        db, p1, approved_scenario,
        action_log=[
            {"sequence_number": 1, "verb": "scan", "target": "h1", "elapsed_seconds": 10, "cost": 5},
            {"sequence_number": 2, "verb": "escalate", "target": None, "elapsed_seconds": 20, "cost": 5},
        ],
        evidence_session_id=session.id,
    )
    p2, _ = await _make_participant(db, client_org)
    await _make_action_run(
        db, p2, approved_scenario,
        action_log=[{"sequence_number": 1, "verb": "escalate", "target": None, "elapsed_seconds": 15, "cost": 5}],
        evidence_session_id=session.id,
    )
    await db.commit()

    resp = await client.get(f"/api/v1/cmmc/evidence-sessions/{session.id}/aggregate", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["escalations"]) == 2
    assert all(e["verb"] == "escalate" for e in body["escalations"])
    attributed_users = {e["participant_user_id"] for e in body["escalations"]}
    assert attributed_users == {p1.id, p2.id}
