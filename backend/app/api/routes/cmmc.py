"""Phase 2.5 CMMC Evidence Layer — onboarding & invitation flow (build-order item 2).

Two routers, matching the two trust levels from the approved design:
- `admin_router` (/admin/cmmc): staff-only. The ONLY way a new ConsultingOrg
  comes into existence — "gated, not self-serve, for v1" per Femi's explicit
  call: a ConsultingOrg issues signed compliance artifacts under
  BreachReplay's name, so who can issue is a trust decision.
- `router` (/cmmc): any authenticated user. Consultant-to-consultant
  invites, client-org creation, and invite redemption all live here — an
  existing consultant_admin acts within their own org without staff
  involvement.

Every invite (staff-bootstrapping the first admin, a consultant_admin
inviting a peer, a consultant_admin inviting a client_participant) goes
through the single `_issue_invite` helper, so the email-binding / single-
use / expiry guarantees exist in exactly one place.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_admin
from app.db.session import get_db
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.membership import Membership
from app.models.user import User
from app.schemas.cmmc import (
    ClientOrgCreate,
    ClientOrgOut,
    ConsultingOrgCreate,
    ConsultingOrgOut,
    InviteCreate,
    InvitePreviewOut,
)
from app.schemas.user import MessageResponse
from app.services.cmmc_access import get_client_orgs_for_user, get_consulting_org_admin_membership
from app.services.cmmc_invites import (
    delete_cmmc_invite,
    emails_match,
    get_cmmc_invite,
    new_invite_token,
    redeem_invite_for_user,
    store_cmmc_invite,
)

router = APIRouter(prefix="/cmmc", tags=["cmmc"])
admin_router = APIRouter(prefix="/admin/cmmc", tags=["cmmc-admin"])


async def _issue_invite(
    *,
    email: str,
    role: str,
    org_name: str,
    consulting_org_id: str | None,
    client_org_id: str | None,
    invited_by_user_id: str,
) -> None:
    token = new_invite_token()
    await store_cmmc_invite(
        token,
        email=email,
        role=role,
        consulting_org_id=consulting_org_id,
        client_org_id=client_org_id,
        invited_by_user_id=invited_by_user_id,
    )
    from app.core.config import settings
    from app.services.email_service import send_cmmc_invite_email

    invite_url = f"{settings.FRONTEND_URL}/cmmc/invitations/{token}"
    send_cmmc_invite_email(email, org_name, role, invite_url)


@admin_router.post("/consulting-orgs", response_model=ConsultingOrgOut, status_code=201)
async def create_consulting_org(
    payload: ConsultingOrgCreate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Staff-only. The sole entry point for a brand-new ConsultingOrg —
    also issues the invite for its first consultant_admin, reusing the
    same token/redemption path as every other invite rather than a
    separate bootstrap mechanism."""
    org = ConsultingOrg(name=payload.name)
    db.add(org)
    await db.flush()

    await _issue_invite(
        email=payload.admin_email,
        role="consultant_admin",
        org_name=org.name,
        consulting_org_id=org.id,
        client_org_id=None,
        invited_by_user_id=current_admin.id,
    )
    await db.commit()
    return org


@router.post("/consulting-orgs/{consulting_org_id}/invitations", response_model=MessageResponse)
async def invite_consultant_admin(
    consulting_org_id: str,
    payload: InviteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """An existing consultant_admin invites a peer into their own
    ConsultingOrg — no staff involvement, per the approved design."""
    membership = await get_consulting_org_admin_membership(db, current_user, consulting_org_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Consulting org not found")

    org = await db.get(ConsultingOrg, consulting_org_id)
    await _issue_invite(
        email=payload.email,
        role="consultant_admin",
        org_name=org.name,
        consulting_org_id=consulting_org_id,
        client_org_id=None,
        invited_by_user_id=current_user.id,
    )
    await db.commit()
    return MessageResponse(message=f"Invitation sent to {payload.email}")


@router.post("/consulting-orgs/{consulting_org_id}/client-orgs", response_model=ClientOrgOut, status_code=201)
async def create_client_org(
    consulting_org_id: str,
    payload: ClientOrgCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A consultant_admin onboards a new client by creating its ClientOrg
    record — a prerequisite to inviting any client_participant into it."""
    membership = await get_consulting_org_admin_membership(db, current_user, consulting_org_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Consulting org not found")

    client_org = ClientOrg(
        consulting_org_id=consulting_org_id,
        name=payload.name,
        poc_name=payload.poc_name,
        poc_email=payload.poc_email,
        irp_reference=payload.irp_reference,
    )
    db.add(client_org)
    await db.commit()
    await db.refresh(client_org)
    return client_org


@router.post("/client-orgs/{client_org_id}/invitations", response_model=MessageResponse)
async def invite_client_participant(
    client_org_id: str,
    payload: InviteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A consultant_admin invites a client_participant into a ClientOrg —
    scoped to the consulting org that actually owns it, so a consultant_
    admin of org A can't invite anyone into org B's client."""
    client_org = await db.get(ClientOrg, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    membership = await get_consulting_org_admin_membership(db, current_user, client_org.consulting_org_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    await _issue_invite(
        email=payload.email,
        role="client_participant",
        org_name=client_org.name,
        consulting_org_id=None,
        client_org_id=client_org_id,
        invited_by_user_id=current_user.id,
    )
    await db.commit()
    return MessageResponse(message=f"Invitation sent to {payload.email}")


@router.get("/invitations/{token}", response_model=InvitePreviewOut)
async def preview_invitation(token: str, db: AsyncSession = Depends(get_db)):
    """No auth — lets a frontend show "you're invited to join X as a Y"
    before the person decides whether to register or log in."""
    invite = await get_cmmc_invite(token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")

    if invite["consulting_org_id"]:
        org = await db.get(ConsultingOrg, invite["consulting_org_id"])
    else:
        org = await db.get(ClientOrg, invite["client_org_id"])
    org_name = org.name if org is not None else "BreachReplay"
    return InvitePreviewOut(org_name=org_name, role=invite["role"])


@router.post("/invitations/{token}/redeem", response_model=MessageResponse)
async def redeem_invitation(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """For an already-logged-in existing user. The email-binding check
    here is the exact protection against a forwarded invite link granting
    access to someone other than the invited person."""
    invite = await get_cmmc_invite(token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found or expired")
    if not emails_match(invite["email"], current_user.email):
        raise HTTPException(status_code=400, detail="This invite was issued to a different email address")

    await redeem_invite_for_user(db, current_user, invite)
    await delete_cmmc_invite(token)
    await db.commit()
    return MessageResponse(message="Invitation accepted")


@router.get("/me/consulting-org", response_model=ConsultingOrgOut)
async def get_my_consulting_org(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Membership).where(
            Membership.user_id == current_user.id,
            Membership.role == "consultant_admin",
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Not a consultant admin of any consulting org")

    org = await db.get(ConsultingOrg, membership.consulting_org_id)
    return org


@router.get("/client-orgs", response_model=list[ClientOrgOut])
async def list_my_client_orgs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_client_orgs_for_user(db, current_user)
