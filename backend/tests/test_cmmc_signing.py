"""
Tests for the Phase 2.5 CMMC Evidence Layer's signing and tamper-evidence
(build-order item 7): app/core/cmmc_signing.py, app/services/
cmmc_issuance.py, and the /pack/issue + /cmmc/verify/* routes.

Per Femi's approved design: issuance is a discrete, one-time, idempotent
event, gated by the same dual-signoff export-readiness check as item 6;
verification never leaks whether an unknown document_id exists vs. a
known one with a mismatched hash; a rotated signing key must not
invalidate verification of packs signed before the rotation; and the
verification response includes the issuing ConsultingOrg's name (already
on the cover the caller is holding) but nothing about session content.
"""
import hashlib
import uuid
from datetime import datetime

import pytest

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User

pytestmark = pytest.mark.asyncio

# Must match conftest.py's cmmc_signing_keys autouse fixture exactly —
# that fixture provides these globally so every test (not just this file)
# has a working signing key without needing to opt in.
_KEY_A_ID = "test-key-a"
_KEY_B_ID = "test-key-b"


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


async def _make_run(db, user: User, scenario, session: EvidenceSession) -> ActionRun:
    run = ActionRun(
        user_id=user.id, scenario_id=scenario.id, seed=1, mode="scenario",
        action_log=[{"sequence_number": 1, "verb": "isolate", "target": "host-1", "elapsed_seconds": 60, "cost": 10}],
        score_breakdown={
            "outcome": "contained", "outcome_base": 0, "evidence_points": 0, "evidence_found": 0, "evidence_total": 0,
            "speed_bonus": 0, "penalty_total": 0, "penalties": [], "collateral": [], "collateral_penalty": 0,
            "total_score": 0, "score_pct": 0.0,
        },
        total_score=0, duration_seconds=60, outcome="contained", evidence_session_id=session.id,
    )
    db.add(run)
    await db.flush()
    return run


BASE = "/api/v1/cmmc/evidence-sessions"
VERIFY_BASE = "/api/v1/cmmc/verify"


async def _fully_signed_session(db, approved_scenario) -> dict:
    consultant, consultant_token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    await _make_run(db, participant, approved_scenario, session)
    await db.commit()
    return {
        "session": session, "client_org": client_org, "org": org,
        "consultant_token": consultant_token, "participant_token": participant_token,
    }


async def _dual_sign(client, ctx):
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))


# ── issuance ─────────────────────────────────────────────────────────────

async def test_issue_creates_signed_record_and_pdf_file(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    headers = auth_headers(ctx["consultant_token"])

    resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["evidence_session_id"] == ctx["session"].id
    assert body["key_id"] == _KEY_A_ID
    assert len(body["sha256_hash"]) == 64

    import os
    pdf_path = os.path.join(settings.ISSUED_PACKS_DIR, f"{body['id']}.pdf")
    assert os.path.exists(pdf_path)
    with open(pdf_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    assert actual_hash == body["sha256_hash"]


async def test_issue_is_idempotent(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    headers = auth_headers(ctx["consultant_token"])

    first = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=headers)
    second = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["sha256_hash"] == second.json()["sha256_hash"]


async def test_issue_blocked_without_both_signoffs(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))
    assert resp.status_code == 400
    assert set(resp.json()["detail"]["missing"]) == {"client_signoff", "consultant_signoff"}


async def test_issue_requires_consultant_admin(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["participant_token"]))
    assert resp.status_code == 404


async def test_pack_download_serves_issued_bytes_not_a_fresh_render(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    headers = auth_headers(ctx["consultant_token"])

    not_yet = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=headers)
    assert not_yet.status_code == 404

    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=headers)
    issued_hash = issue_resp.json()["sha256_hash"]

    download1 = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=headers)
    download2 = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=headers)
    assert download1.status_code == 200
    assert download1.content == download2.content
    assert hashlib.sha256(download1.content).hexdigest() == issued_hash


# ── verification ─────────────────────────────────────────────────────────

async def test_verify_known_good_pack_succeeds(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))
    doc_id, doc_hash = issue_resp.json()["id"], issue_resp.json()["sha256_hash"]

    resp = await client.get(f"{VERIFY_BASE}/{doc_id}", params={"hash": doc_hash})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["key_id"] == _KEY_A_ID
    assert body["consulting_org_name"] == ctx["org"].name


async def test_verify_single_altered_byte_fails(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))
    doc_id = issue_resp.json()["id"]

    download = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=auth_headers(ctx["consultant_token"]))
    tampered = bytearray(download.content)
    tampered[100] ^= 0xFF  # flip one byte
    tampered_hash = hashlib.sha256(bytes(tampered)).hexdigest()

    resp = await client.get(f"{VERIFY_BASE}/{doc_id}", params={"hash": tampered_hash})
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


async def test_verify_unknown_document_id_returns_not_found_without_leaking(client):
    resp = await client.get(f"{VERIFY_BASE}/{uuid.uuid4()}", params={"hash": "a" * 64})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body.get("issued_at") is None
    assert body.get("consulting_org_name") is None


async def test_verify_response_shape_identical_for_unknown_id_and_hash_mismatch(client, db, approved_scenario):
    """Same {valid: false} shape either way — a caller must not be able
    to tell "this document_id doesn't exist" apart from "it exists but
    your hash is wrong"."""
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))
    doc_id = issue_resp.json()["id"]

    wrong_hash_resp = await client.get(f"{VERIFY_BASE}/{doc_id}", params={"hash": "b" * 64})
    unknown_id_resp = await client.get(f"{VERIFY_BASE}/{uuid.uuid4()}", params={"hash": "b" * 64})
    assert wrong_hash_resp.json() == unknown_id_resp.json() == {
        "valid": False, "issued_at": None, "key_id": None, "consulting_org_name": None,
    }


async def test_verify_response_includes_org_name_but_not_session_content(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))
    doc_id, doc_hash = issue_resp.json()["id"], issue_resp.json()["sha256_hash"]

    resp = await client.get(f"{VERIFY_BASE}/{doc_id}", params={"hash": doc_hash})
    body = resp.json()
    assert set(body.keys()) == {"valid", "issued_at", "key_id", "consulting_org_name"}
    assert ctx["client_org"].name not in str(body)
    assert ctx["session"].id not in str(body)


# ── key rotation ─────────────────────────────────────────────────────────

async def test_rotated_key_still_verifies_old_signature(client, db, approved_scenario, monkeypatch):
    ctx = await _fully_signed_session(db, approved_scenario)
    await _dual_sign(client, ctx)
    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))
    doc_id, doc_hash = issue_resp.json()["id"], issue_resp.json()["sha256_hash"]
    assert issue_resp.json()["key_id"] == _KEY_A_ID

    # Rotate: key B becomes active for NEW issuance. Key A stays in
    # CMMC_SIGNING_KEYS (never removed) so old signatures keep verifying.
    monkeypatch.setattr(settings, "CMMC_ACTIVE_SIGNING_KEY_ID", _KEY_B_ID)

    resp = await client.get(f"{VERIFY_BASE}/{doc_id}", params={"hash": doc_hash})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
    assert resp.json()["key_id"] == _KEY_A_ID  # still the key that actually signed it


async def test_public_keys_endpoint_lists_all_known_keys_including_rotated_out_ones(client, monkeypatch):
    monkeypatch.setattr(settings, "CMMC_ACTIVE_SIGNING_KEY_ID", _KEY_B_ID)
    resp = await client.get(f"{VERIFY_BASE}/public-keys")
    assert resp.status_code == 200
    key_ids = {row["key_id"] for row in resp.json()}
    assert key_ids == {_KEY_A_ID, _KEY_B_ID}
    assert all(row["algorithm"] == "ed25519" for row in resp.json())
