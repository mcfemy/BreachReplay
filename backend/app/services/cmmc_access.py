"""
Phase 2.5 CMMC Evidence Layer — access scoping (build-order item 1).

Cross-tenant leakage is the highest-severity failure mode in this layer
(PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md section 4: "isolation is a blocking
requirement"). These helpers are the single place that decides "can this
user see this row" for the CMMC tenancy tree — written and tested now,
before any route exists, so later build-order items (routes, PDF
generation) have one already-proven scoping primitive to call rather than
each re-deriving their own WHERE clause.

Every lookup-by-id function here returns `None` on "exists but you can't
see it" — never raises, never distinguishes "doesn't exist" from "not
yours" in its return value. Mirrors this repo's existing cross-org
isolation pattern (backend/tests/test_admin.py's
test_toggle_user_active_wrong_org_fails: a 404, not a 403, so a caller
can't fingerprint another tenant's ids by the error shape they get back).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cmmc_org import ClientOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User


async def get_consulting_org_admin_membership(
    db: AsyncSession, user: User, consulting_org_id: str,
) -> Optional[Membership]:
    """None unless `user` is specifically a consultant_admin of this exact
    ConsultingOrg — stricter than get_client_orgs_for_user, which also
    returns orgs visible to client_participants. Build-order item 2's
    invitation and client-org-creation routes are consultant_admin-only
    actions; every route that needs "is this caller allowed to act as an
    admin of org X" calls this once and 404s on None, rather than
    re-deriving the query per route."""
    result = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.consulting_org_id == consulting_org_id,
            Membership.role == "consultant_admin",
        )
    )
    return result.scalar_one_or_none()


async def get_client_participant_membership(
    db: AsyncSession, user: User, client_org_id: str,
) -> Optional[Membership]:
    """Mirrors get_consulting_org_admin_membership's shape for the other
    role — None unless `user` is specifically a client_participant of this
    exact ClientOrg. Build-order item 5's client-signoff route is the
    first place a client_participant's Membership grants a WRITE action,
    not just scoped reads."""
    result = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.client_org_id == client_org_id,
            Membership.role == "client_participant",
        )
    )
    return result.scalar_one_or_none()


async def get_client_orgs_for_user(db: AsyncSession, user: User) -> list[ClientOrg]:
    """Every ClientOrg this user can legitimately see:
    - a consultant_admin sees every ClientOrg under their ConsultingOrg
      (there may be several — one RPO, many clients);
    - a client_participant sees only their own ClientOrg (there is at most
      one — a participant's Membership is scoped to a single client_org_id
      by ck_membership_role_matches_org).
    A user with no Membership at all sees nothing — empty list, not an error."""
    memberships = (
        await db.execute(select(Membership).where(Membership.user_id == user.id))
    ).scalars().all()

    consulting_org_ids = [m.consulting_org_id for m in memberships if m.consulting_org_id is not None]
    client_org_ids = [m.client_org_id for m in memberships if m.client_org_id is not None]

    if not consulting_org_ids and not client_org_ids:
        return []

    result = await db.execute(
        select(ClientOrg).where(
            (ClientOrg.consulting_org_id.in_(consulting_org_ids)) | (ClientOrg.id.in_(client_org_ids))
        )
    )
    return list(result.scalars().all())


async def get_evidence_session_scoped(
    db: AsyncSession, user: User, evidence_session_id: str,
) -> Optional[EvidenceSession]:
    """The EvidenceSession, IFF this user has a Membership that grants
    access to its ClientOrg (directly, as a client_participant, or via the
    owning ConsultingOrg, as a consultant_admin) — `None` otherwise,
    whether the row doesn't exist at all or exists but belongs to a tenant
    this user has no membership in. Callers must not distinguish those two
    cases in what they show the user (see module docstring).

    NOTE: this grants BOTH roles read access, which is correct for
    whatever build-order item 5's client-facing sign-off eventually needs.
    Build-order item 3 (designation) must NOT use this — see
    get_evidence_session_for_consulting_admin below."""
    session = await db.get(EvidenceSession, evidence_session_id)
    if session is None:
        return None

    visible_client_org_ids = {org.id for org in await get_client_orgs_for_user(db, user)}
    if session.client_org_id not in visible_client_org_ids:
        return None
    return session


async def get_client_org_for_consulting_admin(
    db: AsyncSession, user: User, client_org_id: str,
) -> Optional[ClientOrg]:
    """None unless `user` is a consultant_admin of the ConsultingOrg that
    owns this exact ClientOrg — the same check item 2's client-org
    invitation route already did inline, factored out here since
    build-order item 3 needs it in three places (list runs, create
    session, list sessions), all consultant_admin-only."""
    client_org = await db.get(ClientOrg, client_org_id)
    if client_org is None:
        return None
    membership = await get_consulting_org_admin_membership(db, user, client_org.consulting_org_id)
    if membership is None:
        return None
    return client_org


async def get_evidence_session_for_consulting_admin(
    db: AsyncSession, user: User, evidence_session_id: str,
) -> Optional[EvidenceSession]:
    """Consultant-admin-only variant of get_evidence_session_scoped above.
    Build-order item 3 (designation) is deliberately consultant-only —
    "compliance is an export, never an experience" means a
    client_participant must get the exact same None a stranger would from
    every item-3 route, not a scoped read. Every item-3 route that
    operates on an existing EvidenceSession calls this, never the
    broader helper above."""
    session = await db.get(EvidenceSession, evidence_session_id)
    if session is None:
        return None
    client_org = await get_client_org_for_consulting_admin(db, user, session.client_org_id)
    if client_org is None:
        return None
    return session
