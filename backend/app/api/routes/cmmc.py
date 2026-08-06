"""Phase 2.5 CMMC Evidence Layer — onboarding/invitations (item 2) and
EvidenceSession designation (item 3).

Two routers, matching the two trust levels from item 2's approved design:
- `admin_router` (/admin/cmmc): staff-only. The ONLY way a new ConsultingOrg
  comes into existence — "gated, not self-serve, for v1" per Femi's explicit
  call: a ConsultingOrg issues signed compliance artifacts under
  BreachReplay's name, so who can issue is a trust decision.
- `router` (/cmmc): any authenticated user, individually scoped per route.
  Consultant-to-consultant invites, client-org creation, invite
  redemption, and every item-3 designation/aggregation route live here.

Every invite (staff-bootstrapping the first admin, a consultant_admin
inviting a peer, a consultant_admin inviting a client_participant) goes
through the single `_issue_invite` helper, so the email-binding / single-
use / expiry guarantees exist in exactly one place.

Every item-3 WRITE route (create/update session, designate/remove runs)
is consultant_admin-only — "compliance is an export, never an experience"
(Femi's item-3 constraint) means a client_participant must get the same
404 a stranger would. Enforced via get_evidence_session_for_consulting_admin
/ get_client_org_for_consulting_admin (app/services/cmmc_access.py), which
never grant a client_participant's membership as sufficient.

Item 5 deliberately WIDENS the two read routes (GET .../evidence-sessions/
{id} and .../aggregate) to item 1's broader get_evidence_session_scoped —
"the client attests the record is accurate" requires the client to be
able to see it first. Every write route stays exactly as consultant-only
as before; only reads opened up, and only to the session's own client
org's participants. Item 5's own write routes split further: lessons/
remediation stay consultant-authored (get_client_org_for_consulting_admin
/ get_evidence_session_for_consulting_admin), while the two sign-off
routes are each gated to the ONE role that attestation belongs to
(get_consulting_org_admin_membership for consultant_signoff,
get_client_participant_membership for client_signoff) — the first routes
in this whole layer where a client_participant's own Membership grants a
write action, not just a scoped read.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cmmc_signing import SigningNotConfigured
from app.core.cmmc_signing import public_keys as signing_public_keys
from app.core.config import settings
from app.core.security import get_current_user, require_admin
from app.db.session import get_db
from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.scenario import Scenario
from app.models.user import User
from app.schemas.cmmc import (
    ClientOrgCreate,
    ClientOrgOut,
    ConsultingOrgCreate,
    ConsultingOrgOut,
    DesignateRunsRequest,
    EvidenceSessionAggregateOut,
    EvidenceSessionCreate,
    EvidenceSessionDetailOut,
    EvidenceSessionOut,
    EvidenceSessionUpdate,
    ExportReadinessOut,
    InviteCreate,
    InvitePreviewOut,
    IssuedPackOut,
    LessonCreate,
    LessonOut,
    LessonUpdate,
    NotificationMatrixEntryCreate,
    NotificationMatrixEntryOut,
    NotificationMatrixEntryUpdate,
    PublicKeyOut,
    RemediationItemCreate,
    RemediationItemOut,
    RemediationItemUpdate,
    RunSummaryOut,
    SignoffOut,
    VerifyPackOut,
)
from app.schemas.user import MessageResponse
from app.services.cmmc_access import (
    get_client_org_for_consulting_admin,
    get_client_orgs_for_user,
    get_client_participant_membership,
    get_consulting_org_admin_membership,
    get_evidence_session_for_consulting_admin,
    get_evidence_session_scoped,
)
from app.services.cmmc_after_action import (
    AfterActionError,
    add_lesson,
    add_remediation_item,
    evidence_session_export_blockers,
    record_signoff,
    remove_lesson,
    remove_remediation_item,
    update_lesson,
    update_remediation_item,
)
from app.services.cmmc_evidence import (
    build_evidence_session_aggregate,
    designate_runs,
    list_client_org_runs,
    runs_with_participant_names,
)
from app.services.cmmc_invites import (
    delete_cmmc_invite,
    emails_match,
    get_cmmc_invite,
    new_invite_token,
    redeem_invite_for_user,
    store_cmmc_invite,
)
from app.services.cmmc_issuance import get_issued_pack, issue_pack, verify_pack
from app.services.cmmc_notification_matrix import (
    add_notification_matrix_entry,
    list_notification_matrix,
    remove_notification_matrix_entry,
    update_notification_matrix_entry,
)
from app.services.cmmc_pdf import build_pack_payload, render_evidence_pack_html

router = APIRouter(prefix="/cmmc", tags=["cmmc"])
admin_router = APIRouter(prefix="/admin/cmmc", tags=["cmmc-admin"])
# Build-order item 7. No auth, deliberately: an assessor holding a PDF
# must be able to verify it without a BreachReplay account. Separate
# router (not just unauthenticated routes on `router`) so the "this is
# public" boundary is visible at a glance, not buried in per-route
# Depends() absence.
verify_router = APIRouter(prefix="/cmmc/verify", tags=["cmmc-verify"])


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


# ── Build-order item 3: EvidenceSession designation from completed runs ────

@router.get("/client-orgs/{client_org_id}/runs", response_model=list[RunSummaryOut])
async def list_client_org_runs_route(
    client_org_id: str,
    designated: bool | None = None,
    scenario_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Completed runs belonging to this client org's participants — every
    ActionRun row IS a completed run by construction (see
    action_run_store.finalize's docstring: a row is written exactly once,
    at run.end; an in-progress run lives only in the in-process
    ActionRunStore, never here), so there's no separate "is it done yet"
    filter to apply. `designated=false` (the common case) narrows to runs
    not yet in any evidence session."""
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    runs = await list_client_org_runs(db, client_org_id, designated=designated, scenario_id=scenario_id)
    return await runs_with_participant_names(db, runs)


@router.post("/client-orgs/{client_org_id}/evidence-sessions", response_model=EvidenceSessionOut, status_code=201)
async def create_evidence_session(
    client_org_id: str,
    payload: EvidenceSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates an empty session — no runs yet. Runs are added afterward via
    POST .../runs, since designation happens on rows that already exist
    ("compliance is an export, never an experience"): there's no reason a
    session's creation and its run-designation should be the same
    request, and separating them lets a consultant fix a session's title/
    date before deciding which runs belong in it."""
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    session = EvidenceSession(
        client_org_id=client_org_id,
        title=payload.title,
        scenario_id=payload.scenario_id,
        exercise_date=payload.exercise_date,
        created_by_user_id=current_user.id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/client-orgs/{client_org_id}/evidence-sessions", response_model=list[EvidenceSessionOut])
async def list_client_org_evidence_sessions(
    client_org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    result = await db.execute(
        select(EvidenceSession).where(EvidenceSession.client_org_id == client_org_id)
        .order_by(EvidenceSession.exercise_date.desc())
    )
    return list(result.scalars().all())


@router.get("/evidence-sessions/{evidence_session_id}", response_model=EvidenceSessionDetailOut)
async def get_evidence_session(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The session plus a lightweight per-run summary — outcome and score,
    not the full merged timeline/collateral breakdown (see .../aggregate
    for that) — plus the AAR content (item 5). Readable by BOTH
    consultant_admin and client_participant of this session
    (get_evidence_session_scoped, not the consultant-only helper item 3's
    write routes still use) — "the client attests the record is
    accurate" requires being able to see it first."""
    session = await get_evidence_session_scoped(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    result = await db.execute(select(ActionRun).where(ActionRun.evidence_session_id == evidence_session_id))
    runs = list(result.scalars().all())
    run_summaries = await runs_with_participant_names(db, runs)

    return EvidenceSessionDetailOut(
        id=session.id,
        client_org_id=session.client_org_id,
        title=session.title,
        scenario_id=session.scenario_id,
        exercise_date=session.exercise_date,
        created_at=session.created_at,
        runs=run_summaries,
        lessons_learned=session.lessons_learned,
        remediation_items=session.remediation_items,
        client_signoff=session.client_signoff,
        consultant_signoff=session.consultant_signoff,
    )


def _require_not_finalized(session: EvidenceSession) -> None:
    """consultant_signoff is item 5's (not-yet-built) after-action stub
    column — unused today, but this IS what "before it's finalised" means
    once item 5 ships, so the check goes in now rather than being
    forgotten later. Can never trigger yet since nothing sets it."""
    if session.consultant_signoff is not None:
        raise HTTPException(status_code=400, detail="Evidence session already finalized")


@router.patch("/evidence-sessions/{evidence_session_id}", response_model=EvidenceSessionOut)
async def update_evidence_session(
    evidence_session_id: str,
    payload: EvidenceSessionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")
    _require_not_finalized(session)

    if payload.title is not None:
        session.title = payload.title
    if payload.scenario_id is not None:
        session.scenario_id = payload.scenario_id
    if payload.exercise_date is not None:
        session.exercise_date = payload.exercise_date

    await db.commit()
    await db.refresh(session)
    return session


@router.post("/evidence-sessions/{evidence_session_id}/runs", response_model=MessageResponse)
async def designate_runs_route(
    evidence_session_id: str,
    payload: DesignateRunsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All-or-nothing over the whole batch — see
    app.services.cmmc_evidence.designate_runs's docstring. A run already
    in a DIFFERENT session is rejected loudly (409), never silently
    re-parented; a run already in THIS session is treated as a no-op."""
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")
    _require_not_finalized(session)

    errors = await designate_runs(db, session, payload.run_ids)
    if errors:
        raise HTTPException(
            status_code=409,
            detail={"message": "One or more runs failed validation; nothing was designated", "errors": errors},
        )

    await db.commit()
    return MessageResponse(message=f"Designated {len(payload.run_ids)} run(s)")


@router.delete("/evidence-sessions/{evidence_session_id}/runs/{run_id}", response_model=MessageResponse)
async def remove_run_from_evidence_session(
    evidence_session_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")
    _require_not_finalized(session)

    run = await db.get(ActionRun, run_id)
    if run is None or run.evidence_session_id != evidence_session_id:
        raise HTTPException(status_code=404, detail="Run not found in this evidence session")

    run.evidence_session_id = None
    await db.commit()
    return MessageResponse(message="Run removed from evidence session")


@router.get("/evidence-sessions/{evidence_session_id}/aggregate", response_model=EvidenceSessionAggregateOut)
async def get_evidence_session_aggregate(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Widened for item 5, same reasoning as get_evidence_session above:
    "the record" a client_participant is attesting to includes the merged
    timeline and per-participant outcomes, not just the lesson text."""
    session = await get_evidence_session_scoped(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    return await build_evidence_session_aggregate(db, session)


# ── Build-order item 4: notification matrix CRUD ────────────────────────────
# Consultant_admin-only, same gating as every other CMMC route so far — the
# spec doesn't say who maintains the matrix, and this matches how the
# consultant already enters ClientOrg.poc_name/irp_reference on the
# client's behalf rather than the client self-serving it. Easy to open up
# to client-side read access later; not assumed here.

@router.get("/client-orgs/{client_org_id}/notification-matrix", response_model=list[NotificationMatrixEntryOut])
async def list_client_org_notification_matrix(
    client_org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")
    return list_notification_matrix(client_org)


@router.post("/client-orgs/{client_org_id}/notification-matrix", response_model=NotificationMatrixEntryOut, status_code=201)
async def add_client_org_notification_matrix_entry(
    client_org_id: str,
    payload: NotificationMatrixEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    # mode="json": serializes last_validated (a datetime) to an ISO string
    # before it goes into the JSONB list — the column has no custom JSON
    # serializer configured (app/db/session.py), so a raw Python datetime
    # object would fail to serialize on commit.
    entry = add_notification_matrix_entry(client_org, payload.model_dump(mode="json"))
    await db.commit()
    return entry


@router.patch("/client-orgs/{client_org_id}/notification-matrix/{entry_id}", response_model=NotificationMatrixEntryOut)
async def update_client_org_notification_matrix_entry(
    client_org_id: str,
    entry_id: str,
    payload: NotificationMatrixEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    changes = payload.model_dump(mode="json", exclude_unset=True)
    updated = update_notification_matrix_entry(client_org, entry_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Notification matrix entry not found")

    await db.commit()
    return updated


@router.delete("/client-orgs/{client_org_id}/notification-matrix/{entry_id}", response_model=MessageResponse)
async def remove_client_org_notification_matrix_entry(
    client_org_id: str,
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_org = await get_client_org_for_consulting_admin(db, current_user, client_org_id)
    if client_org is None:
        raise HTTPException(status_code=404, detail="Client org not found")

    removed = remove_notification_matrix_entry(client_org, entry_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Notification matrix entry not found")

    await db.commit()
    return MessageResponse(message="Notification matrix entry removed")


# ── Build-order item 5: after-action workflow ────────────────────────────────
# Lessons/remediation stay consultant-authored (get_evidence_session_for_
# consulting_admin) — the client's only WRITE action anywhere in this
# layer is signing. See the two signoff routes below for the first place
# a client_participant's own Membership grants a write, and
# get_evidence_session/get_evidence_session_aggregate above for the
# widened reads that make "attest to the record" possible.

@router.post("/evidence-sessions/{evidence_session_id}/lessons", response_model=LessonOut, status_code=201)
async def add_evidence_session_lesson(
    evidence_session_id: str,
    payload: LessonCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    try:
        lesson = await add_lesson(
            db, session,
            text=payload.text,
            anchor=payload.anchor.model_dump() if payload.anchor else None,
            irp_incorporated=payload.irp_incorporated,
            irp_note=payload.irp_note,
            created_by=current_user,
        )
    except AfterActionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    return lesson


@router.patch("/evidence-sessions/{evidence_session_id}/lessons/{lesson_id}", response_model=LessonOut)
async def update_evidence_session_lesson(
    evidence_session_id: str,
    lesson_id: str,
    payload: LessonUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    # model_dump() already recurses LessonAnchorIn -> a plain dict when
    # payload.anchor is set — update_lesson re-validates that raw dict
    # against the session's actual runs (see validate_lesson_anchor),
    # never trusting a client-supplied anchor as-is.
    changes = payload.model_dump(exclude_unset=True)

    try:
        updated = await update_lesson(db, session, lesson_id, changes)
    except AfterActionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    await db.commit()
    return updated


@router.delete("/evidence-sessions/{evidence_session_id}/lessons/{lesson_id}", response_model=MessageResponse)
async def remove_evidence_session_lesson(
    evidence_session_id: str,
    lesson_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    try:
        removed = remove_lesson(session, lesson_id)
    except AfterActionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail="Lesson not found")

    await db.commit()
    return MessageResponse(message="Lesson removed")


@router.post("/evidence-sessions/{evidence_session_id}/remediation-items", response_model=RemediationItemOut, status_code=201)
async def add_evidence_session_remediation_item(
    evidence_session_id: str,
    payload: RemediationItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deliberately not gated on sign-off state, unlike lessons — "track
    remediation items to closure" is an ongoing process that continues
    after the exercise and after sign-off; see cmmc_after_action's module
    docstring."""
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    item = add_remediation_item(session, payload.model_dump(mode="json"))
    await db.commit()
    return item


@router.patch("/evidence-sessions/{evidence_session_id}/remediation-items/{item_id}", response_model=RemediationItemOut)
async def update_evidence_session_remediation_item(
    evidence_session_id: str,
    item_id: str,
    payload: RemediationItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    changes = payload.model_dump(mode="json", exclude_unset=True)
    updated = update_remediation_item(session, item_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    await db.commit()
    return updated


@router.delete("/evidence-sessions/{evidence_session_id}/remediation-items/{item_id}", response_model=MessageResponse)
async def remove_evidence_session_remediation_item(
    evidence_session_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    removed = remove_remediation_item(session, item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    await db.commit()
    return MessageResponse(message="Remediation item removed")


@router.post("/evidence-sessions/{evidence_session_id}/signoff/consultant", response_model=SignoffOut)
async def sign_evidence_session_as_consultant(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Consultant attests to facilitation. Any consultant_admin of the
    owning ConsultingOrg may sign — not restricted to whoever created the
    session, same scoping item 3's other consultant routes already use."""
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    try:
        signoff = record_signoff(session, "consultant_signoff", current_user)
    except AfterActionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    await db.commit()
    return signoff


@router.post("/evidence-sessions/{evidence_session_id}/signoff/client", response_model=SignoffOut)
async def sign_evidence_session_as_client(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Client attests the record is accurate. Resolves the session via the
    broad scoped-read first (so an unrelated user gets 404, not a
    role-mismatch signal), then requires the caller specifically be a
    client_participant of THIS session's client org — a consultant_admin
    who can otherwise read this session gets the same 404 here, never a
    403 that would confirm "you can see this, you're just the wrong
    role."""
    session = await get_evidence_session_scoped(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    membership = await get_client_participant_membership(db, current_user, session.client_org_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    try:
        signoff = record_signoff(session, "client_signoff", current_user)
    except AfterActionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    await db.commit()
    return signoff


@router.get("/evidence-sessions/{evidence_session_id}/export-readiness", response_model=ExportReadinessOut)
async def get_evidence_session_export_readiness(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Femi's structural gate, read side: either legitimate role can check
    readiness. Build-order item 6 (PDF generation) calls
    evidence_session_export_blockers directly at export time — this route
    is the same check, exposed so a UI can show "waiting on client
    sign-off" ahead of actually trying to export."""
    session = await get_evidence_session_scoped(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    blockers = evidence_session_export_blockers(session)
    return ExportReadinessOut(ready=not blockers, missing=blockers)


# ── Build-order item 6: evidence pack (PDF) ──────────────────────────────────

@router.get("/evidence-sessions/{evidence_session_id}/pack")
async def download_evidence_session_pack(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Build-order item 7: serves the STORED, previously-issued bytes —
    never a fresh render. A signed artifact has to be issued once and
    served identically forever after; re-rendering on every download
    would mean a future Chromium/Playwright upgrade could silently change
    what "the issued pack" contains, breaking the hash it was signed
    under. 404 if nothing has been issued yet — call .../pack/issue
    first. Scoped via get_evidence_session_scoped (both roles) — the
    client should be able to download the artifact they attested to,
    same reasoning as item 5's widened reads."""
    session = await get_evidence_session_scoped(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    issued = await get_issued_pack(db, evidence_session_id)
    if issued is None:
        raise HTTPException(status_code=404, detail="No pack has been issued for this evidence session yet")

    with open(issued.pdf_path, "rb") as f:
        pdf_bytes = f.read()

    safe_title = session.title.replace(" ", "-")
    filename = f"BreachReplay-Evidence-Pack-{safe_title}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/evidence-sessions/{evidence_session_id}/pack/issue", response_model=IssuedPackOut, status_code=201)
async def issue_evidence_session_pack(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The one, discrete, one-way act of signing and permanently
    recording an evidence pack — consultant_admin-only (matches every
    other lifecycle-managing action in this layer), gated on the same
    dual-signoff export-readiness check as the download route.
    Idempotent: re-calling this for an already-issued session returns the
    existing record rather than re-signing or overwriting it."""
    session = await get_evidence_session_for_consulting_admin(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    blockers = evidence_session_export_blockers(session)
    if blockers:
        raise HTTPException(
            status_code=400,
            detail={"message": "Evidence session is not ready to export", "missing": blockers},
        )

    try:
        issued = await issue_pack(
            db, session, issued_by=current_user, verify_url_base=f"{settings.FRONTEND_URL}/api/v1/cmmc/verify",
        )
    except SigningNotConfigured as e:
        raise HTTPException(status_code=500, detail=str(e))

    await db.commit()
    return issued


@router.get("/evidence-sessions/{evidence_session_id}/pack/view", response_class=HTMLResponse)
async def view_evidence_session_pack(
    evidence_session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The HTML half of the pack: same export-readiness gate and scoping
    as the PDF download route above, rendered for in-browser viewing with
    a "Download PDF" button pointing back at that same route — the record
    is reviewable before/instead of downloading it, not just downloadable
    blind."""
    session = await get_evidence_session_scoped(db, current_user, evidence_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Evidence session not found")

    blockers = evidence_session_export_blockers(session)
    if blockers:
        raise HTTPException(
            status_code=400,
            detail={"message": "Evidence session is not ready to export", "missing": blockers},
        )

    client_org = await db.get(ClientOrg, session.client_org_id)
    consulting_org = await db.get(ConsultingOrg, client_org.consulting_org_id)
    scenario = await db.get(Scenario, session.scenario_id)

    payload = await build_pack_payload(db, session, consulting_org, client_org, scenario)
    return HTMLResponse(content=render_evidence_pack_html(payload, show_download_button=True))


# ── Build-order item 7: public verification (no auth) ───────────────────────

@verify_router.get("/public-keys", response_model=list[PublicKeyOut])
async def list_signing_public_keys():
    """Every known key, not just the currently-active one — so a
    signature made before a rotation stays independently checkable
    offline, forever, by anyone holding this response, without ever
    calling this endpoint (or any of ours) again."""
    return signing_public_keys()


@verify_router.get("/{document_id}", response_model=VerifyPackOut)
async def verify_issued_pack(document_id: str, hash: str, db: AsyncSession = Depends(get_db)):
    """No auth. Reveals only whether the artifact was issued and hasn't
    been altered, plus the issuing org's name (already printed on the
    cover of the PDF the caller is holding — confirming it matches what's
    on file is the entire point). Never the pack's contents, never
    anything about client_org/participants/lessons. An unknown
    document_id and a hash that doesn't match a real one return the
    IDENTICAL {valid: false} shape — no existence leakage, matching this
    whole layer's established discipline, extended here to an anonymous
    public caller instead of an authenticated wrong-tenant one."""
    result = await verify_pack(db, document_id, hash)
    if result is None:
        return VerifyPackOut(valid=False)
    return VerifyPackOut(**result)
