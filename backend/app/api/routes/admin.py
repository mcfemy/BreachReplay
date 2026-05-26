from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.db.session import get_db
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.scenario import Scenario
from app.schemas.user import UserOut
from app.schemas.scenario import ScenarioOut
from app.core.security import require_admin, get_current_user
from app.services.audit import log_action

router = APIRouter(prefix="/admin", tags=["admin"])


class RoleUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=20)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: Optional[str]
    organization_id: Optional[str]
    action: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    details: Optional[dict]
    created_at: str


def _translate_user_out(user: User) -> UserOut:
    """Helper to translate database role values back to the Phase 3 schema roles for clients."""
    uo = UserOut.model_validate(user)
    if uo.role == "owner":
        uo.role = "ciso"
    elif uo.role == "viewer":
        uo.role = "observer"
    return uo


@router.get("/users", response_model=List[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Retrieve all users registered under the admin's organization."""
    result = await db.execute(
        select(User).where(User.organization_id == current_admin.organization_id)
    )
    return [_translate_user_out(u) for u in result.scalars().all()]


@router.patch("/users/{user_id}/toggle-active", response_model=UserOut)
async def toggle_user_active(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Toggle a user's is_active status in the database."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Admins cannot deactivate themselves")

    result = await db.execute(
        select(User).where(User.id == user_id, User.organization_id == current_admin.organization_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in organization")

    user.is_active = not user.is_active

    await log_action(
        db,
        action="user_deactivated" if not user.is_active else "user_activated",
        user_id=current_admin.id,
        organization_id=current_admin.organization_id,
        details={"target_user_id": user_id, "target_user_email": user.email},
    )
    await db.commit()  # Single commit for both the status change and the audit log

    return _translate_user_out(user)


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: str,
    payload: RoleUpdatePayload,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Update a user's access controls role (admin, ciso, analyst, observer)."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Admins cannot change their own role")

    # Validate role enum value
    allowed_roles = {"admin", "ciso", "analyst", "observer"}
    if payload.role.lower() not in allowed_roles:
        raise HTTPException(status_code=400, detail=f"Role must be one of {allowed_roles}")

    result = await db.execute(
        select(User).where(User.id == user_id, User.organization_id == current_admin.organization_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in organization")

    # Translate from Phase 3 schema role to DB SQLAlchemy Enum role
    role_api_to_db = {
        "admin": "admin",
        "ciso": "owner",
        "analyst": "analyst",
        "observer": "viewer",
    }

    old_role = user.role
    user.role = role_api_to_db[payload.role.lower()]

    await log_action(
        db,
        action="user_role_updated",
        user_id=current_admin.id,
        organization_id=current_admin.organization_id,
        details={
            "target_user_id": user_id,
            "old_role": old_role,
            "new_role": payload.role.lower(),
        },
    )
    await db.commit()  # Single commit for both the role change and the audit log

    return _translate_user_out(user)


@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Retrieve paginated audit logs for the admin's organization."""
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.organization_id == current_admin.organization_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()
    
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "organization_id": l.organization_id,
            "action": l.action,
            "ip_address": l.ip_address,
            "user_agent": l.user_agent,
            "details": l.details,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


@router.get("/scenarios/pending", response_model=List[ScenarioOut])
async def list_pending_scenarios(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Return all draft and review scenarios for admin review."""
    result = await db.execute(
        select(Scenario).where(Scenario.status.in_(["draft", "review"])).order_by(Scenario.created_at.desc())
    )
    return [ScenarioOut.model_validate(s) for s in result.scalars().all()]


@router.get("/compliance-analytics")
async def get_compliance_analytics(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    from sqlalchemy.orm import selectinload
    from app.models.scenario import Scenario
    from app.models.session import SimulationSession
    from app.models.user import User
    from app.models.organization import Organization
    from app.models.breach_document import BreachDocument

    # Fetch organization and count uploaded documents
    org_res = await db.execute(select(Organization).where(Organization.id == current_admin.organization_id))
    org = org_res.scalar_one_or_none()
    org_name = org.name if org else "Personal Sandbox"
    org_tier = org.tier if org else "starter"

    docs_res = await db.execute(select(BreachDocument).where(BreachDocument.organization_id == current_admin.organization_id))
    docs_count = len(docs_res.scalars().all())
    docs_limit = 3 if org_tier == "starter" else 999


    # 1. NIST & MITRE coverage per scenario
    scenarios_res = await db.execute(
        select(Scenario).where(
            (Scenario.status == "approved")
            & ((Scenario.is_private == False) | (Scenario.owner_org_id == current_admin.organization_id))
        )
    )
    scenarios = scenarios_res.scalars().all()

    scenario_coverage = [
        {
            "id": s.id,
            "title": s.title,
            "industry": s.industry_vertical,
            "difficulty": s.difficulty,
            "mitre_techniques": s.mitre_techniques or [],
            "nist_controls": s.nist_controls or [],
            "frameworks": s.regulatory_frameworks or [],
        }
        for s in scenarios
    ]

    # 2. Fetch completed sessions in organization (with participants, decisions, scenario)
    sessions_res = await db.execute(
        select(SimulationSession)
        .where(SimulationSession.organization_id == current_admin.organization_id, SimulationSession.status == "completed")
        .options(
            selectinload(SimulationSession.participants),
            selectinload(SimulationSession.decisions),
            selectinload(SimulationSession.scenario),
        )
    )
    sessions = sessions_res.scalars().all()

    # 3. Per-Analyst Performance
    users_res = await db.execute(select(User).where(User.organization_id == current_admin.organization_id))
    users = users_res.scalars().all()

    # Build O(n) lookup: user_id -> sessions they participated in
    user_session_map: dict[str, list] = {u.id: [] for u in users}
    for s in sessions:
        for p in s.participants:
            if p.user_id in user_session_map:
                user_session_map[p.user_id].append(s)

    analyst_performance = []
    for u in users:
        user_sessions = user_session_map[u.id]
        sessions_completed = len(user_sessions)
        avg_score = (
            round(sum(s.team_score or 0 for s in user_sessions) / sessions_completed, 1)
            if sessions_completed > 0
            else 0
        )

        # Filter decisions made by this user in these sessions
        user_decisions = [d for s in user_sessions for d in s.decisions if d.user_id == u.id]
        decisions_made = len(user_decisions)
        decisions_correct = sum(1 for d in user_decisions if d.is_correct)
        accuracy = round((decisions_correct / decisions_made) * 100, 1) if decisions_made > 0 else 0

        analyst_performance.append(
            {
                "user_id": u.id,
                "full_name": u.full_name or u.email,
                "email": u.email,
                "role": u.role,
                "sessions_completed": sessions_completed,
                "average_score": avg_score,
                "decisions_made": decisions_made,
                "decisions_correct": decisions_correct,
                "accuracy_rate": accuracy,
            }
        )

    # 4. Scenario Calibration Recommendation
    calibrations = []
    for s in scenarios:
        scenario_sessions = [sess for sess in sessions if sess.scenario_id == s.id]
        play_count = len(scenario_sessions)
        avg_play_score = (
            round(sum(sess.team_score or 0 for sess in scenario_sessions) / play_count, 1)
            if play_count > 0
            else None
        )

        calibrated_difficulty = s.difficulty
        if play_count > 0 and avg_play_score is not None:
            if avg_play_score < 60.0:
                calibrated_difficulty = "expert"
            elif avg_play_score > 85.0:
                calibrated_difficulty = "awareness"
            else:
                calibrated_difficulty = "practitioner"

        calibrations.append(
            {
                "scenario_id": s.id,
                "title": s.title,
                "designed_difficulty": s.difficulty,
                "play_count": play_count,
                "avg_score": avg_play_score,
                "calibrated_difficulty": calibrated_difficulty,
                "is_calibrated": calibrated_difficulty == s.difficulty,
            }
        )

    # 5. Private Scenario Library
    private_res = await db.execute(
        select(Scenario)
        .where(
            (Scenario.is_private == True)  # noqa: E712
            & (Scenario.owner_org_id == current_admin.organization_id)
            & (Scenario.status == "approved")
        )
        .order_by(Scenario.created_at.desc())
    )
    private_scenarios_raw = private_res.scalars().all()

    private_scenarios = []
    for ps in private_scenarios_raw:
        ps_sessions = [s for s in sessions if s.scenario_id == ps.id]
        last_played_at = None
        if ps_sessions:
            most_recent = max(
                ps_sessions,
                key=lambda s: s.completed_at.isoformat() if s.completed_at else "",
            )
            last_played_at = most_recent.completed_at.isoformat() if most_recent.completed_at else None
        private_scenarios.append(
            {
                "id": ps.id,
                "title": ps.title,
                "industry": ps.industry_vertical,
                "difficulty": ps.difficulty,
                "play_count": ps.play_count,
                "avg_score": ps.avg_score,
                "last_played_at": last_played_at,
                "mitre_techniques": ps.mitre_techniques or [],
                "nist_controls": ps.nist_controls or [],
                "source_reference": ps.source_reference,
            }
        )

    # 6. Completed Evidence Logs
    compliance_evidence = []
    for s in sessions:
        audit_notes = (
            s.debrief_report.get("compliance_evidence", {}).get("audit_notes")
            if s.debrief_report
            else None
        )
        if not audit_notes:
            audit_notes = "Annual SOC tabletop simulation training satisfying NIST SP 800-61 parameters."

        compliance_evidence.append(
            {
                "session_id": s.id,
                "scenario_title": s.scenario.title if s.scenario else "N/A",
                "completed_at": s.completed_at.isoformat() if s.completed_at else "N/A",
                "score": s.team_score,
                "participant_count": len(s.participants),
                "frameworks": s.scenario.regulatory_frameworks if s.scenario else [],
                "audit_notes": audit_notes,
            }
        )

    # 7. Readiness Score (0-100, four 25-pt components)
    now_utc = datetime.now(timezone.utc)
    cutoff_90 = now_utc - timedelta(days=90)
    recent_sessions = [
        s for s in sessions
        if s.completed_at and s.completed_at.replace(tzinfo=timezone.utc) >= cutoff_90
    ]
    freq_score = min(len(recent_sessions) / 4 * 25, 25.0)
    scored = [s for s in sessions if s.team_score is not None]
    avg_val = (sum(s.team_score for s in scored) / len(scored)) if scored else 0.0
    score_score = (avg_val / 100) * 25
    all_nist = set(c for s in scenarios for c in (s.nist_controls or []))
    exercised_nist = set(
        c for sess in sessions for c in ((sess.scenario.nist_controls or []) if sess.scenario else [])
    )
    nist_score = (len(exercised_nist) / max(len(all_nist), 1)) * 25
    private_score = min(len(private_scenarios_raw) / 5 * 25, 25.0)
    readiness_score = round(freq_score + score_score + nist_score + private_score, 1)
    readiness_components = {
        "session_frequency": round(freq_score, 1),
        "avg_score": round(score_score, 1),
        "nist_coverage": round(nist_score, 1),
        "proprietary_library": round(private_score, 1),
    }

    # 8. 8-week trend
    trend_data = []
    for week_offset in range(7, -1, -1):
        w_start = now_utc - timedelta(days=(week_offset + 1) * 7)
        w_end = now_utc - timedelta(days=week_offset * 7)
        week_sess = [
            s for s in sessions
            if s.completed_at and w_start <= s.completed_at.replace(tzinfo=timezone.utc) < w_end
        ]
        week_avg = (
            round(sum(s.team_score or 0 for s in week_sess) / len(week_sess), 1)
            if week_sess else None
        )
        trend_data.append({
            "week": w_start.strftime("%m/%d"),
            "sessions": len(week_sess),
            "avg_score": week_avg,
        })

    # 9. Recommendations — unplayed scenarios that patch NIST/MITRE gaps
    failed_nist = set(
        d.nist_control_ref
        for sess in sessions for d in sess.decisions
        if not d.is_correct and d.nist_control_ref
    )
    exercised_mitre = set(
        d.mitre_technique for sess in sessions for d in sess.decisions if d.mitre_technique
    )
    failed_mitre = set(
        d.mitre_technique
        for sess in sessions for d in sess.decisions
        if not d.is_correct and d.mitre_technique
    )
    played_scenario_ids = {s.scenario_id for s in sessions}
    recommendations = []
    for s in scenarios:
        if s.id in played_scenario_ids:
            continue
        sc_nist = set(s.nist_controls or [])
        sc_mitre = set(s.mitre_techniques or [])
        gap_coverage = len(sc_nist & failed_nist) + len(sc_mitre & failed_mitre)
        recommendations.append({
            "id": s.id,
            "title": s.title,
            "difficulty": s.difficulty,
            "industry": s.industry_vertical,
            "estimated_minutes": s.estimated_minutes,
            "new_nist_controls": sorted(sc_nist - exercised_nist),
            "new_mitre_techniques": sorted(sc_mitre - exercised_mitre),
            "gap_coverage": gap_coverage,
        })
    recommendations.sort(key=lambda r: r["gap_coverage"], reverse=True)
    recommendations = recommendations[:5]

    return {
        "organization_name": org_name,
        "organization_tier": org_tier,
        "custom_docs_count": docs_count,
        "custom_docs_limit": docs_limit,
        "readiness_score": readiness_score,
        "readiness_components": readiness_components,
        "readiness_trend": trend_data,
        "recommendations": recommendations,
        "scenario_coverage": scenario_coverage,
        "analyst_performance": analyst_performance,
        "calibrations": calibrations,
        "compliance_evidence": compliance_evidence,
        "private_scenarios": private_scenarios,
    }


@router.get("/compliance-evidence/export")
async def export_compliance_evidence(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from sqlalchemy.orm import selectinload
    from app.models.session import SimulationSession

    sessions_res = await db.execute(
        select(SimulationSession)
        .where(SimulationSession.organization_id == current_admin.organization_id, SimulationSession.status == "completed")
        .options(selectinload(SimulationSession.participants), selectinload(SimulationSession.scenario))
    )
    sessions = sessions_res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Session ID",
            "Scenario Title",
            "Designed Difficulty",
            "Date Completed",
            "NIST Score",
            "Frameworks Exercised",
            "Incident Commander ID",
            "Participant Count",
        ]
    )

    for s in sessions:
        date_str = s.completed_at.strftime("%Y-%m-%d %H:%M UTC") if s.completed_at else "N/A"
        frameworks_str = (
            ", ".join(s.scenario.regulatory_frameworks)
            if s.scenario and s.scenario.regulatory_frameworks
            else "N/A"
        )
        difficulty = s.scenario.difficulty if s.scenario else "N/A"

        writer.writerow(
            [
                s.id,
                s.scenario.title if s.scenario else "N/A",
                difficulty.upper(),
                date_str,
                f"{s.team_score}%" if s.team_score is not None else "N/A",
                frameworks_str,
                s.host_user_id,
                len(s.participants),
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=BreachReplay_Compliance_Evidence.csv"},
    )


class TenantOnboardPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100)
    tier: str = Field(default="starter")


@router.post("/tenants/onboard", status_code=status.HTTP_201_CREATED)
async def onboard_tenant(
    payload: TenantOnboardPayload,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_user),
):
    """Allow platform owners (CISOs) to onboard new organizational tenants."""
    from app.models.organization import Organization

    # Enforce Owner/CISO level authority
    if current_admin.role != "owner":
        raise HTTPException(status_code=403, detail="Platform onboarding requires OWNER/CISO authority")

    # Check slug uniqueness against the normalised (lowercased) value that will be stored
    slug_check = await db.execute(
        select(Organization).where(Organization.slug == payload.slug.lower())
    )
    if slug_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Tenant slug '{payload.slug}' already registered")

    # Validate tier
    allowed_tiers = {"starter", "team", "enterprise", "mssp"}
    if payload.tier.lower() not in allowed_tiers:
        raise HTTPException(status_code=400, detail=f"Billing tier must be one of {allowed_tiers}")

    new_org = Organization(
        name=payload.name,
        slug=payload.slug.lower(),
        tier=payload.tier.lower(),
        is_active=True,
    )
    db.add(new_org)
    await db.commit()

    return {
        "id": new_org.id,
        "name": new_org.name,
        "slug": new_org.slug,
        "tier": new_org.tier,
        "is_active": new_org.is_active,
        "created_at": new_org.created_at.isoformat(),
    }


@router.post("/scenarios/{scenario_id}/version", status_code=status.HTTP_201_CREATED)
async def snapshot_scenario_version(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Snapshot the current state of a private scenario for version history tracking."""
    result = await db.execute(
        select(Scenario).where(
            Scenario.id == scenario_id,
            Scenario.is_private == True,  # noqa: E712
            Scenario.owner_org_id == current_admin.organization_id,
        )
    )
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Private scenario not found in your organization")

    snapshot = {
        "version": scenario.version or 1,
        "snapshotted_at": datetime.now(timezone.utc).isoformat(),
        "title": scenario.title,
        "decision_tree": scenario.decision_tree,
        "alert_sequence": scenario.alert_sequence,
    }
    history = list(scenario.version_history or [])
    history.append(snapshot)
    scenario.version_history = history
    scenario.version = (scenario.version or 1) + 1
    await db.commit()

    return {
        "scenario_id": scenario.id,
        "new_version": scenario.version,
        "snapshot_count": len(history),
    }


@router.get("/task-failures")
async def list_task_failures(
    current_admin: User = Depends(require_admin),
):
    """Return recent Celery task failures stored in Redis. Admins only."""
    import json
    from app.core.redis import get_redis

    r = await get_redis()
    keys = await r.keys("task_failure:*")
    if not keys:
        return []

    raw_values = await r.mget(*keys)
    failures = []
    for raw in raw_values:
        if raw:
            try:
                failures.append(json.loads(raw))
            except Exception:
                pass

    failures.sort(key=lambda f: f.get("timestamp", ""), reverse=True)
    return failures


@router.get("/tenants")
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_user),
):
    """Retrieve all onboarded tenants with user and plays counts."""
    from app.models.organization import Organization
    from sqlalchemy.orm import selectinload

    if current_admin.role != "owner":
        raise HTTPException(status_code=403, detail="Viewing platform tenant logs requires OWNER/CISO authority")

    result = await db.execute(
        select(Organization)
        .options(selectinload(Organization.users), selectinload(Organization.sessions))
        .order_by(Organization.created_at.desc())
    )
    orgs = result.scalars().all()

    return [
        {
            "id": o.id,
            "name": o.name,
            "slug": o.slug,
            "tier": o.tier,
            "is_active": o.is_active,
            "user_count": len(o.users),
            "sessions_count": len(o.sessions),
            "created_at": o.created_at.isoformat(),
        }
        for o in orgs
    ]
