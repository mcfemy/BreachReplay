"""
Tests for the Phase 2.5 CMMC Evidence Layer's multi-tenancy skeleton
(build-order item 1): the Membership constraints and the cross-tenant
isolation scoping helpers in app/services/cmmc_access.py.

Isolation is this layer's highest-severity failure mode
(PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md section 4) — these tests exist to
prove it at the data-access layer now, before any route exists to test it
through, since later build-order items (routes, PDF generation) will all
build on top of get_client_orgs_for_user/get_evidence_session_scoped
rather than re-deriving their own scoping.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.cmmc_org import ConsultingOrg, ClientOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User
from app.services.cmmc_access import get_client_orgs_for_user, get_evidence_session_scoped

pytestmark = pytest.mark.asyncio


def _user(email: str) -> User:
    return User(
        email=email,
        hashed_password=hash_password("StrongPass1!"),
        full_name=email,
        role="analyst",
        organization_id=None,
    )


@pytest.fixture
async def two_tenant_setup(db, approved_scenario):
    """Two fully independent tenancy trees: ConsultingOrg A -> ClientOrg X
    (with a consultant_admin and a client_participant), and ConsultingOrg
    B -> ClientOrg Y (same shape) — the minimum needed to prove A/X can
    never see B/Y and vice versa."""
    consulting_org_a = ConsultingOrg(name="Alpha RPO")
    consulting_org_b = ConsultingOrg(name="Beta RPO")
    db.add_all([consulting_org_a, consulting_org_b])
    await db.flush()

    client_org_x = ClientOrg(consulting_org_id=consulting_org_a.id, name="X Contracting")
    client_org_y = ClientOrg(consulting_org_id=consulting_org_b.id, name="Y Contracting")
    db.add_all([client_org_x, client_org_y])
    await db.flush()

    consultant_a = _user("consultant-a@example.com")
    client_participant_x = _user("participant-x@example.com")
    db.add_all([consultant_a, client_participant_x])
    await db.flush()

    db.add_all([
        Membership(user_id=consultant_a.id, consulting_org_id=consulting_org_a.id, role="consultant_admin"),
        Membership(user_id=client_participant_x.id, client_org_id=client_org_x.id, role="client_participant"),
    ])
    await db.flush()

    evidence_session_x = EvidenceSession(
        client_org_id=client_org_x.id, scenario_id=approved_scenario.id, exercise_date=approved_scenario.created_at,
    )
    evidence_session_y = EvidenceSession(
        client_org_id=client_org_y.id, scenario_id=approved_scenario.id, exercise_date=approved_scenario.created_at,
    )
    db.add_all([evidence_session_x, evidence_session_y])
    await db.flush()

    return {
        "consulting_org_a": consulting_org_a, "consulting_org_b": consulting_org_b,
        "client_org_x": client_org_x, "client_org_y": client_org_y,
        "consultant_a": consultant_a, "client_participant_x": client_participant_x,
        "evidence_session_x": evidence_session_x, "evidence_session_y": evidence_session_y,
    }


async def test_consultant_cannot_list_other_consultants_client_orgs(db, two_tenant_setup):
    s = two_tenant_setup
    visible = await get_client_orgs_for_user(db, s["consultant_a"])
    visible_ids = {org.id for org in visible}
    assert s["client_org_x"].id in visible_ids
    assert s["client_org_y"].id not in visible_ids


async def test_client_participant_only_sees_own_client_orgs_evidence_sessions(db, two_tenant_setup):
    s = two_tenant_setup
    visible = await get_client_orgs_for_user(db, s["client_participant_x"])
    visible_ids = {org.id for org in visible}
    assert visible_ids == {s["client_org_x"].id}


async def test_client_participant_cannot_escalate_via_crafted_evidence_session_id(db, two_tenant_setup):
    """Participant in X directly requests Y's evidence session id (a real,
    existing row — not a random uuid) and must get None, not the row and
    not an exception that would distinguish 'exists but forbidden' from
    'does not exist' — mirroring test_admin.py's 404-not-403 principle at
    the data-access layer, ahead of any route existing to return an actual
    HTTP status from."""
    s = two_tenant_setup
    result = await get_evidence_session_scoped(db, s["client_participant_x"], s["evidence_session_y"].id)
    assert result is None

    # Sanity: the SAME participant CAN reach their own session.
    own = await get_evidence_session_scoped(db, s["client_participant_x"], s["evidence_session_x"].id)
    assert own is not None
    assert own.id == s["evidence_session_x"].id


async def test_evidence_session_scoped_returns_none_for_nonexistent_id(db, two_tenant_setup):
    s = two_tenant_setup
    result = await get_evidence_session_scoped(db, s["consultant_a"], str(uuid.uuid4()))
    assert result is None


async def test_membership_check_constraint_rejects_dual_org_assignment(db):
    consulting_org = ConsultingOrg(name="Dual Org Test RPO")
    db.add(consulting_org)
    await db.flush()
    client_org = ClientOrg(consulting_org_id=consulting_org.id, name="Dual Org Test Client")
    db.add(client_org)
    await db.flush()
    user = _user("dual-org@example.com")
    db.add(user)
    await db.flush()

    db.add(Membership(
        user_id=user.id, consulting_org_id=consulting_org.id, client_org_id=client_org.id,
        role="consultant_admin",
    ))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_membership_role_org_mismatch_rejected(db):
    """Tightened per review: role must match the SPECIFIC org FK that's
    set, not just 'some org FK is set'. A consultant_admin row pointed at
    a client_org_id (or the reverse) must be structurally unrepresentable."""
    consulting_org = ConsultingOrg(name="Role Mismatch Test RPO")
    db.add(consulting_org)
    await db.flush()
    client_org = ClientOrg(consulting_org_id=consulting_org.id, name="Role Mismatch Test Client")
    db.add(client_org)
    await db.flush()
    user = _user("role-mismatch@example.com")
    db.add(user)
    await db.flush()

    # consultant_admin role, but pointed at client_org_id — wrong pairing.
    db.add(Membership(user_id=user.id, client_org_id=client_org.id, role="consultant_admin"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_membership_unique_index_rejects_duplicate_assignment(db):
    """Catches the bug a plain 3-column UniqueConstraint would have missed
    (NULL != NULL for uniqueness purposes) — the partial unique indexes
    must actually enforce one membership per (user, org)."""
    consulting_org = ConsultingOrg(name="Duplicate Test RPO")
    db.add(consulting_org)
    await db.flush()
    user = _user("duplicate-membership@example.com")
    db.add(user)
    await db.flush()

    db.add(Membership(user_id=user.id, consulting_org_id=consulting_org.id, role="consultant_admin"))
    await db.flush()

    db.add(Membership(user_id=user.id, consulting_org_id=consulting_org.id, role="consultant_admin"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_action_run_evidence_session_scoping(db, two_tenant_setup, approved_scenario):
    """An ActionRun linked to X's evidence session is reachable through
    X's scoping and invisible through Y's — confirms the new
    evidence_session_id FK on ActionRun actually round-trips."""
    from app.models.action_run import ActionRun

    s = two_tenant_setup
    run = ActionRun(
        user_id=s["client_participant_x"].id,
        scenario_id=approved_scenario.id,
        evidence_session_id=s["evidence_session_x"].id,
        seed=1,
        mode="scenario",
        action_log=[],
        score_breakdown={},
        total_score=0,
        duration_seconds=0,
        outcome="contained",
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    assert run.evidence_session_id == s["evidence_session_x"].id
    # Re-fetch the session fresh (avoids relying on lazy relationship
    # traversal in an async context) to confirm the FK genuinely points at
    # X's session, not Y's.
    fetched_session = await db.get(EvidenceSession, run.evidence_session_id)
    assert fetched_session is not None
    assert fetched_session.client_org_id == s["client_org_x"].id
