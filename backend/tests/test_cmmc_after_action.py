"""
HTTP-level tests for the Phase 2.5 CMMC Evidence Layer's after-action
workflow (build-order item 5): lessons learned (with the run-moment
anchor validated at write time), remediation items, and dual sign-off.

Per Femi's three explicit requirements for this item:
1. Dual sign-off is a hard, structural export gate — tested via
   evidence_session_export_blockers / GET .../export-readiness, never
   just documented as a convention item 6 is expected to follow.
2. This is the first item where a client_participant ACTS on data (signs
   client_signoff) — isolation tests extend to that role: cross-client-org
   isolation, role-appropriate action separation (a consultant can't sign
   as the client and vice versa), and confirming the read-widening from
   item 3's routes did NOT also widen write access.
3. The lesson->run-moment anchor is validated against the session's real
   designated runs and their real action_log, not just stored as trusted
   freeform ids — tested directly (wrong run, bad sequence_number).
"""
import uuid
from datetime import datetime

import pytest

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


async def _make_session(db, client_org: ClientOrg, scenario) -> EvidenceSession:
    session = EvidenceSession(
        client_org_id=client_org.id, title="Session", scenario_id=scenario.id, exercise_date=datetime.utcnow(),
    )
    db.add(session)
    await db.flush()
    return session


async def _make_run(db, user: User, scenario, session: EvidenceSession, *, action_log=None) -> ActionRun:
    run = ActionRun(
        user_id=user.id,
        scenario_id=scenario.id,
        seed=1,
        mode="scenario",
        action_log=action_log or [{"sequence_number": 1, "verb": "isolate", "target": "host-3", "elapsed_seconds": 340, "cost": 10}],
        score_breakdown={
            "outcome": "contained", "outcome_base": 0, "evidence_points": 0, "evidence_found": 1, "evidence_total": 2,
            "speed_bonus": 0, "penalty_total": 0, "penalties": [], "collateral": [], "collateral_penalty": 0,
            "total_score": 100, "score_pct": 50.0,
        },
        total_score=100,
        duration_seconds=600,
        outcome="contained",
        evidence_session_id=session.id,
    )
    db.add(run)
    await db.flush()
    return run


LESSON_BASE = f"/api/v1/cmmc/evidence-sessions"


# ── lesson anchor validation (requirement 3) ────────────────────────────────

async def test_add_lesson_without_anchor_allowed(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    await db.commit()

    resp = await client.post(f"{LESSON_BASE}/{session.id}/lessons", json={"text": "General observation"}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["anchor"] is None


async def test_add_lesson_with_valid_anchor_denormalizes_fields(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, _ = await _make_participant(db, client_org)
    run = await _make_run(db, participant, approved_scenario, session)
    await db.commit()

    resp = await client.post(
        f"{LESSON_BASE}/{session.id}/lessons",
        json={"text": "Isolation happened late", "anchor": {"run_id": run.id, "sequence_number": 1}},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    anchor = resp.json()["anchor"]
    assert anchor["verb"] == "isolate"
    assert anchor["target"] == "host-3"
    assert anchor["elapsed_seconds"] == 340
    assert anchor["participant_user_id"] == participant.id
    assert anchor["participant_name"] == participant.full_name


async def test_add_lesson_anchor_run_not_in_session_rejected(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, _ = await _make_participant(db, client_org)
    # Run exists but was never designated into this session.
    other_session = await _make_session(db, client_org, approved_scenario)
    run = await _make_run(db, participant, approved_scenario, other_session)
    await db.commit()

    resp = await client.post(
        f"{LESSON_BASE}/{session.id}/lessons",
        json={"text": "x", "anchor": {"run_id": run.id, "sequence_number": 1}},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_add_lesson_anchor_bad_sequence_number_rejected(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, _ = await _make_participant(db, client_org)
    run = await _make_run(db, participant, approved_scenario, session)
    await db.commit()

    resp = await client.post(
        f"{LESSON_BASE}/{session.id}/lessons",
        json={"text": "x", "anchor": {"run_id": run.id, "sequence_number": 999}},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_update_and_delete_lesson(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    await db.commit()
    headers = auth_headers(token)

    create_resp = await client.post(f"{LESSON_BASE}/{session.id}/lessons", json={"text": "Original"}, headers=headers)
    lesson_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{LESSON_BASE}/{session.id}/lessons/{lesson_id}", json={"irp_incorporated": "yes", "irp_note": "Added to v3"}, headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["text"] == "Original"
    assert update_resp.json()["irp_incorporated"] == "yes"

    delete_resp = await client.delete(f"{LESSON_BASE}/{session.id}/lessons/{lesson_id}", headers=headers)
    assert delete_resp.status_code == 200


# ── AAR content lock vs. remediation staying unlocked ───────────────────────

async def test_lessons_locked_after_either_signoff(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()
    headers = auth_headers(token)

    # Consultant-only sign first -> lessons lock.
    sign_resp = await client.post(f"{LESSON_BASE}/{session.id}/signoff/consultant", headers=headers)
    assert sign_resp.status_code == 200
    blocked = await client.post(f"{LESSON_BASE}/{session.id}/lessons", json={"text": "too late"}, headers=headers)
    assert blocked.status_code == 400


async def test_lessons_locked_after_client_signoff_alone(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()

    sign_resp = await client.post(f"{LESSON_BASE}/{session.id}/signoff/client", headers=auth_headers(participant_token))
    assert sign_resp.status_code == 200
    blocked = await client.post(f"{LESSON_BASE}/{session.id}/lessons", json={"text": "too late"}, headers=auth_headers(token))
    assert blocked.status_code == 400


async def test_remediation_item_crud_and_status_transition(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    await db.commit()
    headers = auth_headers(token)
    base = f"{LESSON_BASE}/{session.id}/remediation-items"

    create_resp = await client.post(
        base, json={"description": "Patch host-3", "owner": "IT Ops", "due_date": "2026-09-01T00:00:00"}, headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    item = create_resp.json()
    assert item["status"] == "open"
    item_id = item["id"]

    close_resp = await client.patch(f"{base}/{item_id}", json={"status": "closed", "closure_note": "Patched 2026-09-05"}, headers=headers)
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "closed"
    assert close_resp.json()["closure_note"] == "Patched 2026-09-05"

    delete_resp = await client.delete(f"{base}/{item_id}", headers=headers)
    assert delete_resp.status_code == 200


async def test_remediation_items_remain_editable_after_both_signoffs(client, db, approved_scenario):
    """Deliberate asymmetry vs. lessons: POA&M tracking continues after
    sign-off — closing an item weeks later is the whole point."""
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()
    headers = auth_headers(token)

    await client.post(f"{LESSON_BASE}/{session.id}/signoff/consultant", headers=headers)
    await client.post(f"{LESSON_BASE}/{session.id}/signoff/client", headers=auth_headers(participant_token))

    create_resp = await client.post(
        f"{LESSON_BASE}/{session.id}/remediation-items",
        json={"description": "Post-signoff item", "owner": "IT Ops", "due_date": "2026-09-01T00:00:00"},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text

    patch_resp = await client.patch(
        f"{LESSON_BASE}/{session.id}/remediation-items/{create_resp.json()['id']}",
        json={"status": "closed"}, headers=headers,
    )
    assert patch_resp.status_code == 200


# ── sign-off: reject-on-repeat, role-appropriate, structural export gate ──

async def test_consultant_signoff_success_and_reject_on_repeat(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    await db.commit()
    headers = auth_headers(token)

    first = await client.post(f"{LESSON_BASE}/{session.id}/signoff/consultant", headers=headers)
    assert first.status_code == 200
    assert first.json()["signed_by_name"] is not None

    second = await client.post(f"{LESSON_BASE}/{session.id}/signoff/consultant", headers=headers)
    assert second.status_code == 409


async def test_client_signoff_success_and_reject_on_repeat(client, db, approved_scenario):
    _, _, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()
    headers = auth_headers(participant_token)

    first = await client.post(f"{LESSON_BASE}/{session.id}/signoff/client", headers=headers)
    assert first.status_code == 200

    second = await client.post(f"{LESSON_BASE}/{session.id}/signoff/client", headers=headers)
    assert second.status_code == 409


async def test_consultant_cannot_sign_as_client_and_vice_versa(client, db, approved_scenario):
    _, consultant_token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()

    consultant_signs_as_client = await client.post(
        f"{LESSON_BASE}/{session.id}/signoff/client", headers=auth_headers(consultant_token),
    )
    assert consultant_signs_as_client.status_code == 404

    participant_signs_as_consultant = await client.post(
        f"{LESSON_BASE}/{session.id}/signoff/consultant", headers=auth_headers(participant_token),
    )
    assert participant_signs_as_consultant.status_code == 404


async def test_export_readiness_reflects_dual_signoff_gate(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()
    headers = auth_headers(token)

    initial = await client.get(f"{LESSON_BASE}/{session.id}/export-readiness", headers=headers)
    assert initial.json() == {"ready": False, "missing": ["client_signoff", "consultant_signoff"]}

    await client.post(f"{LESSON_BASE}/{session.id}/signoff/consultant", headers=headers)
    after_one = await client.get(f"{LESSON_BASE}/{session.id}/export-readiness", headers=headers)
    assert after_one.json() == {"ready": False, "missing": ["client_signoff"]}

    await client.post(f"{LESSON_BASE}/{session.id}/signoff/client", headers=auth_headers(participant_token))
    after_both = await client.get(f"{LESSON_BASE}/{session.id}/export-readiness", headers=headers)
    assert after_both.json() == {"ready": True, "missing": []}


async def test_export_blockers_pure_function_is_the_structural_gate():
    """Direct unit test of the guard Femi required item 6 to call — not
    just the HTTP-level readiness route above, since the pure function IS
    the actual gate any future pack-generation code must call."""
    from app.services.cmmc_after_action import evidence_session_export_blockers

    class _Fake:
        client_signoff = None
        consultant_signoff = None

    fake = _Fake()
    assert evidence_session_export_blockers(fake) == ["client_signoff", "consultant_signoff"]
    fake.client_signoff = {"signed_by_user_id": "x", "signed_by_name": "x", "signed_at": "2026-01-01T00:00:00"}
    assert evidence_session_export_blockers(fake) == ["consultant_signoff"]
    fake.consultant_signoff = {"signed_by_user_id": "y", "signed_by_name": "y", "signed_at": "2026-01-01T00:00:00"}
    assert evidence_session_export_blockers(fake) == []


# ── isolation: extended to the client_participant role (requirement 2) ─────

async def test_client_participant_can_view_session_content(client, db, approved_scenario):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()

    await client.post(f"{LESSON_BASE}/{session.id}/lessons", json={"text": "Visible to client"}, headers=auth_headers(token))

    resp = await client.get(f"{LESSON_BASE}/{session.id}", headers=auth_headers(participant_token))
    assert resp.status_code == 200
    assert resp.json()["lessons_learned"][0]["text"] == "Visible to client"

    aggregate_resp = await client.get(f"{LESSON_BASE}/{session.id}/aggregate", headers=auth_headers(participant_token))
    assert aggregate_resp.status_code == 200


async def test_client_participant_of_other_client_org_cannot_view_or_sign(client, db, approved_scenario):
    _, _, org_a = await _make_consultant_admin(db)
    client_org_a = await _make_client_org(db, org_a)
    session_a = await _make_session(db, client_org_a, approved_scenario)

    _, _, org_b = await _make_consultant_admin(db)
    client_org_b = await _make_client_org(db, org_b)
    _, outsider_token = await _make_participant(db, client_org_b)
    await db.commit()
    headers = auth_headers(outsider_token)

    assert (await client.get(f"{LESSON_BASE}/{session_a.id}", headers=headers)).status_code == 404
    assert (await client.get(f"{LESSON_BASE}/{session_a.id}/aggregate", headers=headers)).status_code == 404
    assert (await client.post(f"{LESSON_BASE}/{session_a.id}/signoff/client", headers=headers)).status_code == 404


async def test_unrelated_user_with_no_membership_cannot_view_session(client, db, approved_scenario):
    _, _, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    await db.commit()

    stranger = _user(_unique_email("stranger"))
    db.add(stranger)
    await db.commit()
    token = create_access_token({"sub": stranger.id})

    assert (await client.get(f"{LESSON_BASE}/{session.id}", headers=auth_headers(token))).status_code == 404
    assert (await client.get(f"{LESSON_BASE}/{session.id}/aggregate", headers=auth_headers(token))).status_code == 404


async def test_client_participant_cannot_write_lessons_or_remediation(client, db, approved_scenario):
    """The legitimate participant of THIS session's own client org — read
    access was deliberately widened, write access was not."""
    _, _, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await db.commit()
    headers = auth_headers(participant_token)

    assert (await client.post(f"{LESSON_BASE}/{session.id}/lessons", json={"text": "x"}, headers=headers)).status_code == 404
    assert (await client.patch(f"{LESSON_BASE}/{session.id}/lessons/{uuid.uuid4()}", json={"text": "x"}, headers=headers)).status_code == 404
    assert (await client.delete(f"{LESSON_BASE}/{session.id}/lessons/{uuid.uuid4()}", headers=headers)).status_code == 404
    assert (await client.post(
        f"{LESSON_BASE}/{session.id}/remediation-items",
        json={"description": "x", "owner": "x", "due_date": "2026-01-01T00:00:00"}, headers=headers,
    )).status_code == 404
    assert (await client.patch(f"{LESSON_BASE}/{session.id}/remediation-items/{uuid.uuid4()}", json={"status": "closed"}, headers=headers)).status_code == 404
    assert (await client.delete(f"{LESSON_BASE}/{session.id}/remediation-items/{uuid.uuid4()}", headers=headers)).status_code == 404
