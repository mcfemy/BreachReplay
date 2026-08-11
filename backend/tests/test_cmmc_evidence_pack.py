"""
Tests for the Phase 2.5 CMMC Evidence Layer's evidence pack generation
(build-order item 6): backend/app/services/cmmc_pdf.py and the
GET /cmmc/evidence-sessions/{id}/pack (+ /pack/view) routes.

Per Femi's approved design: dual sign-off is a hard, structural gate on
generation (not a convention); the pack is scoped the same way item 5's
reads are (both consultant_admin and client_participant of the session's
own client org); and known persistence gaps (tool_output, IOC identities)
are marked "not evidenced by this exercise" via a structural
control-mapping table, never padded. Escalate targets were a third such
gap until Phase 3 (Targeted Escalation & Notification Proportionality)
closed it — see cmmc_pdf.py's build_control_mapping for the current claim
and test_verb_engine.py for the escalate/scoring behavior itself.

Rendering pivoted mid-item from reportlab to HTML + Playwright/Chromium
after visual review found real defects (overlapping/overflowing table
text, hard truncation, no brand identity) — same section structure and
wording, different engine. Per Femi's explicit requirement, this file
also carries a permanent determinism test: item 7 hashes this output, so
a future Chromium/Playwright/pypdf upgrade that reintroduces
non-determinism (Chromium embeds a live /CreationDate/ModDate by default;
pypdf pins them) must fail CI immediately, not be discovered when hash
verification starts failing in production.
"""
import hashlib
import uuid
from datetime import datetime

import pytest

from app.core.security import create_access_token, hash_password
from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User
from app.services.cmmc_pdf import (
    build_control_mapping,
    build_pack_payload,
    generate_evidence_pack_pdf,
    render_evidence_pack_html,
)

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


async def _make_run(db, user: User, scenario, session: EvidenceSession) -> ActionRun:
    run = ActionRun(
        user_id=user.id,
        scenario_id=scenario.id,
        seed=42,
        mode="scenario",
        action_log=[{"sequence_number": 1, "verb": "isolate", "target": "host-3", "elapsed_seconds": 340, "cost": 10}],
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


BASE = "/api/v1/cmmc/evidence-sessions"


async def _fully_signed_session(db, approved_scenario):
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


# ── the structural gate ─────────────────────────────────────────────────────

async def test_pack_blocked_without_both_signoffs(client, db, approved_scenario):
    """Build-order item 7 moved the dual-signoff export-readiness gate
    from the download route onto /pack/issue (see test_cmmc_signing.py's
    test_issue_blocked_without_both_signoffs for that gate itself) —
    /pack now just serves whatever's been issued, so with nothing issued
    yet (because nothing CAN be issued yet) it 404s the same as it would
    for any other not-yet-issued session."""
    ctx = await _fully_signed_session(db, approved_scenario)
    headers = auth_headers(ctx["consultant_token"])

    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=headers)
    assert resp.status_code == 404

    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=headers)
    resp2 = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=headers)
    assert resp2.status_code == 404


async def test_pack_generates_after_both_signoffs(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    consultant_headers = auth_headers(ctx["consultant_token"])
    participant_headers = auth_headers(ctx["participant_token"])

    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=consultant_headers)
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=participant_headers)
    issue_resp = await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=consultant_headers)
    assert issue_resp.status_code == 201, issue_resp.text

    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=consultant_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 1000
    assert resp.content[:4] == b"%PDF"


async def test_pack_pdf_text_contains_honesty_notes(client, db, approved_scenario):
    """Stronger than the byte-count/magic-number check above: extracts the
    actual rendered text (via pypdf, already a dependency) and confirms
    the three "not evidenced" notes and the structural control-mapping
    row actually appear on the page, not just in the payload dict that
    feeds the renderer. Uses a run with a real escalate entry so the
    notifications section's mapping-limitation note actually renders
    (with zero escalations, that sentence is correctly dropped instead —
    covered separately, this test wants the non-trivial case)."""
    from io import BytesIO

    from pypdf import PdfReader

    consultant, consultant_token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    session = await _make_session(db, client_org, approved_scenario)
    participant, participant_token = await _make_participant(db, client_org)
    run = ActionRun(
        user_id=participant.id, scenario_id=approved_scenario.id, seed=42, mode="scenario",
        action_log=[{"sequence_number": 1, "verb": "escalate", "target": None, "elapsed_seconds": 252, "cost": 0}],
        score_breakdown={
            "outcome": "contained", "outcome_base": 0, "evidence_points": 0, "evidence_found": 1, "evidence_total": 2,
            "speed_bonus": 0, "penalty_total": 0, "penalties": [], "collateral": [], "collateral_penalty": 0,
            "total_score": 100, "score_pct": 50.0,
        },
        total_score=100, duration_seconds=600, outcome="contained", evidence_session_id=session.id,
    )
    db.add(run)
    await db.commit()
    ctx = {"session": session, "consultant_token": consultant_token, "participant_token": participant_token}

    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))

    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=auth_headers(ctx["consultant_token"]))
    assert resp.status_code == 200

    reader = PdfReader(BytesIO(resp.content))
    # Normalize whitespace before searching: reportlab's Paragraph
    # word-wrap inserts newlines wherever a line happened to break, so a
    # literal continuous-string search would be fragile against reflow
    # (e.g. font metric changes) rather than actually testing content.
    raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    full_text = " ".join(raw_text.split())

    assert "is not persisted and is not evidenced by this exercise" in full_text
    assert "only aggregate counts are recorded" in full_text
    # Phase 3 — the notifications section's honesty note changed wording
    # (escalate targets/warranted status are now evidenced against the
    # SCENARIO's own authored matrix), but still explicitly disclaims any
    # automated mapping to the org's own declared matrix above it.
    assert "not an automated check against the organization's own declared notification matrix" in full_text
    assert "Investigative actions substantiated by captured tool output" in full_text
    assert "NIST SP 800-171 3.6.3" in full_text


async def test_pack_downloadable_by_client_participant_too(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/pack/issue", headers=auth_headers(ctx["consultant_token"]))

    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=auth_headers(ctx["participant_token"]))
    assert resp.status_code == 200


# ── isolation ────────────────────────────────────────────────────────────────

async def test_pack_scoped_to_session_participants_and_consultant(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))

    _, other_consultant_token, other_org = await _make_consultant_admin(db)
    other_client_org = await _make_client_org(db, other_org)
    _, outsider_participant_token = await _make_participant(db, other_client_org)
    await db.commit()

    assert (await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=auth_headers(other_consultant_token))).status_code == 404
    assert (await client.get(f"{BASE}/{ctx['session'].id}/pack", headers=auth_headers(outsider_participant_token))).status_code == 404


# ── control mapping honesty mechanism ────────────────────────────────────────

async def test_pack_control_mapping_marks_gapped_claims_not_evidenced():
    rows = build_control_mapping()
    by_claim = {r["claim"]: r for r in rows}

    assert by_claim["Investigative actions substantiated by captured tool output"]["evidenced"] is False
    assert by_claim["Specific indicators of compromise identified during response"]["evidenced"] is False
    assert by_claim["Notifications made per the organization's declared obligations"]["evidenced"] is False

    assert by_claim["Incident detected, responded to, and reviewed via a documented after-action process with dual attestation"]["evidenced"] is True
    assert by_claim["Investigative actions evidenced by verb, target, and timing"]["evidenced"] is True

    assert all(r["control"] == "3.6.3" for r in rows)


# ── attacker stage progression, reconstructed from persisted (scenario, seed) ─

async def test_pack_payload_includes_attacker_stage_progression(db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    session = ctx["session"]
    client_org = ctx["client_org"]
    org = ctx["org"]

    payload = await build_pack_payload(db, session, org, client_org, approved_scenario)

    assert len(payload["attacker_stages"]) == 1
    run_stages = payload["attacker_stages"][0]
    assert run_stages["stages"], "expected at least one compiled stage from the scenario's decision tree"
    assert all("trigger_seconds" in s and "compromised_hostnames" in s for s in run_stages["stages"])


async def test_pack_payload_timeline_and_notifications_shape(db, approved_scenario):
    """Sanity: the render payload's aggregate carries the real timeline/
    escalations/notification-matrix data the honesty-mechanism sections
    depend on — not a proxy for asserting on rendered PDF bytes."""
    ctx = await _fully_signed_session(db, approved_scenario)
    payload = await build_pack_payload(db, ctx["session"], ctx["org"], ctx["client_org"], approved_scenario)

    assert payload["aggregate"]["timeline"]
    assert payload["aggregate"]["escalations"] == []  # no escalate verb in the fixture run
    assert payload["notification_matrix"] == []  # none declared


# ── determinism — permanent guard, per Femi's explicit requirement ─────────

async def test_pack_renders_deterministically(db, approved_scenario):
    """item 7 hashes this PDF, so the same session data must produce
    byte-identical output every time. Verified empirically during design
    that Chromium's page.pdf() embeds a live /CreationDate and /ModDate by
    default (the only non-deterministic fields found) and that pinning
    them via pypdf in generate_evidence_pack_pdf fixes it — this test
    makes that guarantee permanent so a future Chromium/Playwright/pypdf
    upgrade that reintroduces non-determinism fails CI immediately."""
    ctx = await _fully_signed_session(db, approved_scenario)
    session = ctx["session"]
    # Signing directly at the DB level (bypassing the HTTP routes) — this
    # test is about renderer determinism, not the signoff flow itself.
    session.consultant_signoff = {"signed_by_user_id": "u1", "signed_by_name": "Alex Rivera", "signed_at": "2026-01-01T00:00:00"}
    session.client_signoff = {"signed_by_user_id": "u2", "signed_by_name": "Jane Doe", "signed_at": "2026-01-01T00:00:00"}
    await db.commit()

    payload = await build_pack_payload(db, session, ctx["org"], ctx["client_org"], approved_scenario)

    pdf1 = await generate_evidence_pack_pdf(payload)
    pdf2 = await generate_evidence_pack_pdf(payload)

    assert hashlib.sha256(pdf1).hexdigest() == hashlib.sha256(pdf2).hexdigest()
    assert pdf1 == pdf2


# ── /pack/view (the HTML half — view before/instead of downloading) ────────

async def test_pack_view_returns_html_with_download_link_and_honesty_notes(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))

    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack/view", headers=auth_headers(ctx["consultant_token"]))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert f"/cmmc/evidence-sessions/{ctx['session'].id}/pack" in body
    assert "is not persisted and is not evidenced by this exercise" in " ".join(body.split())
    assert "NIST SP 800-171 3.6.3" in body


async def test_pack_view_blocked_without_both_signoffs(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack/view", headers=auth_headers(ctx["consultant_token"]))
    assert resp.status_code == 400


async def test_pack_view_scoped_same_as_download(client, db, approved_scenario):
    ctx = await _fully_signed_session(db, approved_scenario)
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/consultant", headers=auth_headers(ctx["consultant_token"]))
    await client.post(f"{BASE}/{ctx['session'].id}/signoff/client", headers=auth_headers(ctx["participant_token"]))

    _, other_consultant_token, _ = await _make_consultant_admin(db)
    await db.commit()

    resp = await client.get(f"{BASE}/{ctx['session'].id}/pack/view", headers=auth_headers(other_consultant_token))
    assert resp.status_code == 404
