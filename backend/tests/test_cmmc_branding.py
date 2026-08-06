"""
Tests for the Phase 2.5 CMMC Evidence Layer's consultant branding
(build-order item 8): app/services/cmmc_branding.py and the four
/cmmc/consulting-orgs/{id}/branding* routes.

Per Femi's approved scope: logo + optional tagline, no accent colors —
upload validation checks REAL content type (not extension, not the
multipart Content-Type header) via Pillow, caps size, and cross-consultant
isolation matches every other CMMC route's 404-not-403 discipline. The
load-bearing test is test_embed_at_issuance_freezes_logo_bytes: item 7's
hash/signature must never change just because a consulting org later
replaces its logo on an already-issued pack.

UPLOAD_DIR is monkeypatched at the app.services.cmmc_branding module
level (not via Settings — cmmc_branding.py deliberately mirrors orgs.py/
ingestion.py's `os.environ.get("UPLOAD_DIR", ...)` convention, read as a
plain module global) to pytest's own tmp_path, mirroring conftest.py's
cmmc_signing_keys fixture: isolated, auto-cleaned, never touches the real
dev UPLOAD_DIR default.
"""
import hashlib
import uuid
from datetime import datetime
from io import BytesIO

import pytest
from PIL import Image

from app.core.security import create_access_token, hash_password
from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/cmmc/consulting-orgs"
SESSIONS_BASE = "/api/v1/cmmc/evidence-sessions"


@pytest.fixture(autouse=True)
def isolated_upload_dir(monkeypatch, tmp_path):
    import app.services.cmmc_branding as cmmc_branding

    monkeypatch.setattr(cmmc_branding, "UPLOAD_DIR", str(tmp_path / "uploads"))


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
    await db.commit()
    token = create_access_token({"sub": user.id})
    return user, token, org


def _png_bytes(color=(200, 50, 50)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(color=(50, 50, 200)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=color).save(buf, format="JPEG")
    return buf.getvalue()


# ── upload validation ────────────────────────────────────────────────────

async def test_upload_accepts_real_png_and_jpeg(client, db):
    _, token, org = await _make_consultant_admin(db)
    headers = auth_headers(token)

    png_resp = await client.post(
        f"{BASE}/{org.id}/branding/logo", headers=headers,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert png_resp.status_code == 201, png_resp.text
    assert png_resp.json() == {"tagline": None, "has_logo": True, "logo_content_type": "image/png"}

    jpeg_resp = await client.post(
        f"{BASE}/{org.id}/branding/logo", headers=headers,
        files={"file": ("logo.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert jpeg_resp.status_code == 201, jpeg_resp.text
    assert jpeg_resp.json()["logo_content_type"] == "image/jpeg"


async def test_upload_rejects_renamed_non_image_file(client, db):
    """The multipart Content-Type header lies (image/png); Pillow's real
    decode is what must catch this, not the declared type or extension."""
    _, token, org = await _make_consultant_admin(db)
    resp = await client.post(
        f"{BASE}/{org.id}/branding/logo", headers=auth_headers(token),
        files={"file": ("logo.png", b"this is definitely not image data", "image/png")},
    )
    assert resp.status_code == 400
    assert "not a valid image" in resp.json()["detail"]


async def test_upload_rejects_oversized_file(client, db):
    _, token, org = await _make_consultant_admin(db)
    oversized = b"\x00" * (2 * 1024 * 1024 + 1)
    resp = await client.post(
        f"{BASE}/{org.id}/branding/logo", headers=auth_headers(token),
        files={"file": ("logo.png", oversized, "image/png")},
    )
    assert resp.status_code == 400
    assert "2MB or smaller" in resp.json()["detail"]


async def test_upload_rejects_svg(client, db):
    _, token, org = await _make_consultant_admin(db)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    resp = await client.post(
        f"{BASE}/{org.id}/branding/logo", headers=auth_headers(token),
        files={"file": ("logo.svg", svg, "image/svg+xml")},
    )
    assert resp.status_code == 400


# ── isolation ─────────────────────────────────────────────────────────────

async def test_consultant_b_cannot_access_consultant_a_branding(client, db):
    _, token_a, org_a = await _make_consultant_admin(db)
    _, token_b, _org_b = await _make_consultant_admin(db)
    headers_a, headers_b = auth_headers(token_a), auth_headers(token_b)

    upload = await client.post(
        f"{BASE}/{org_a.id}/branding/logo", headers=headers_a,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert upload.status_code == 201

    b_upload = await client.post(
        f"{BASE}/{org_a.id}/branding/logo", headers=headers_b,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert b_upload.status_code == 404

    b_view = await client.get(f"{BASE}/{org_a.id}/branding", headers=headers_b)
    assert b_view.status_code == 404

    b_delete = await client.delete(f"{BASE}/{org_a.id}/branding/logo", headers=headers_b)
    assert b_delete.status_code == 404

    b_patch = await client.patch(f"{BASE}/{org_a.id}/branding", headers=headers_b, json={"tagline": "hijacked"})
    assert b_patch.status_code == 404

    # A's own logo is untouched by B's rejected attempts
    a_view = await client.get(f"{BASE}/{org_a.id}/branding", headers=headers_a)
    assert a_view.json()["has_logo"] is True


# ── tagline ───────────────────────────────────────────────────────────────

async def test_tagline_only_update_independent_of_logo(client, db):
    _, token, org = await _make_consultant_admin(db)
    headers = auth_headers(token)

    patch1 = await client.patch(f"{BASE}/{org.id}/branding", headers=headers, json={"tagline": "CMMC Readiness Advisors"})
    assert patch1.status_code == 200
    assert patch1.json() == {"tagline": "CMMC Readiness Advisors", "has_logo": False, "logo_content_type": None}

    upload = await client.post(
        f"{BASE}/{org.id}/branding/logo", headers=headers,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert upload.status_code == 201
    assert upload.json()["tagline"] == "CMMC Readiness Advisors"  # untouched by the logo upload

    patch2 = await client.patch(f"{BASE}/{org.id}/branding", headers=headers, json={"tagline": None})
    assert patch2.status_code == 200
    assert patch2.json() == {"tagline": None, "has_logo": True, "logo_content_type": "image/png"}  # logo untouched

    delete = await client.delete(f"{BASE}/{org.id}/branding/logo", headers=headers)
    assert delete.status_code == 200
    final = await client.get(f"{BASE}/{org.id}/branding", headers=headers)
    assert final.json() == {"tagline": None, "has_logo": False, "logo_content_type": None}


# ── embed-at-issuance (the load-bearing test) ──────────────────────────────

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
    await client.post(f"{SESSIONS_BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{SESSIONS_BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))


async def test_embed_at_issuance_freezes_logo_bytes(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    headers = auth_headers(ctx["consultant_token"])

    upload_a = await client.post(
        f"{BASE}/{ctx['org'].id}/branding/logo", headers=headers,
        files={"file": ("logo-a.png", _png_bytes(color=(200, 50, 50)), "image/png")},
    )
    assert upload_a.status_code == 201

    await _dual_sign(client, ctx)
    issue_resp = await client.post(f"{SESSIONS_BASE}/{ctx['session'].id}/pack/issue", headers=headers)
    assert issue_resp.status_code == 201, issue_resp.text
    issued_hash = issue_resp.json()["sha256_hash"]

    before_download = await client.get(f"{SESSIONS_BASE}/{ctx['session'].id}/pack", headers=headers)
    assert hashlib.sha256(before_download.content).hexdigest() == issued_hash

    # Replace the org's logo entirely (different bytes, still valid PNG).
    upload_b = await client.post(
        f"{BASE}/{ctx['org'].id}/branding/logo", headers=headers,
        files={"file": ("logo-b.png", _png_bytes(color=(10, 200, 10)), "image/png")},
    )
    assert upload_b.status_code == 201

    after_download = await client.get(f"{SESSIONS_BASE}/{ctx['session'].id}/pack", headers=headers)
    assert after_download.status_code == 200
    assert after_download.content == before_download.content
    assert hashlib.sha256(after_download.content).hexdigest() == issued_hash


async def test_pack_with_no_logo_renders_cleanly(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    headers = auth_headers(ctx["consultant_token"])
    await _dual_sign(client, ctx)

    issue_resp = await client.post(f"{SESSIONS_BASE}/{ctx['session'].id}/pack/issue", headers=headers)
    assert issue_resp.status_code == 201, issue_resp.text

    download = await client.get(f"{SESSIONS_BASE}/{ctx['session'].id}/pack", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert len(download.content) > 1000
