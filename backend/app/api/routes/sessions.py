from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.db.session import get_db
from app.models.session import SimulationSession, SessionParticipant, SessionDecision
from app.models.scenario import Scenario
from app.models.user import User
from app.schemas.session import SessionCreate, SessionOut, DecisionSubmit, DecisionResult
from app.core.security import get_current_user
from app.pipeline.tasks import generate_session_debrief
from typing import List

router = APIRouter(prefix="/sessions", tags=["sessions"])


def assert_org_access(session: SimulationSession, user: User) -> None:
    """Raise 403 if the user has no relationship to this session."""
    if session.host_user_id == user.id:
        return
    if user.organization_id and session.organization_id == user.organization_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Scenario).where(Scenario.id == payload.scenario_id, Scenario.status == "approved")
    )
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found or not approved")
    session = SimulationSession(
        scenario_id=payload.scenario_id,
        organization_id=current_user.organization_id,
        host_user_id=current_user.id,
        mode=payload.mode,
        speed_multiplier=payload.speed_multiplier,
    )
    db.add(session)
    await db.flush()
    participant = SessionParticipant(
        session_id=session.id,
        user_id=current_user.id,
        role="incident_commander",
    )
    db.add(participant)
    await db.commit()
    return SessionOut.model_validate(session)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    assert_org_access(session, current_user)
    return SessionOut.model_validate(session)


@router.post("/{session_id}/start", response_model=SessionOut)
async def start_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    assert_org_access(session, current_user)
    if session.host_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the host can start the session")
    if session.status != "waiting":
        raise HTTPException(status_code=400, detail=f"Session cannot be started from status: {session.status}")
    session.status = "active"
    session.started_at = datetime.utcnow()
    await db.commit()
    return SessionOut.model_validate(session)


@router.post("/{session_id}/decisions", response_model=DecisionResult)
async def submit_decision(
    session_id: str,
    payload: DecisionSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    assert_org_access(session, current_user)
    if session.status != "active":
        raise HTTPException(status_code=400, detail="Session is not active")

    scenario_result = await db.execute(select(Scenario).where(Scenario.id == session.scenario_id))
    scenario = scenario_result.scalar_one_or_none()

    decision_tree = scenario.decision_tree or []
    gate = next((g for g in decision_tree if g.get("id") == payload.decision_gate_id), None)
    if not gate:
        raise HTTPException(status_code=404, detail="Decision gate not found")

    is_correct = payload.chosen_option_index == gate["correct_index"]
    consequence = gate["consequence_if_wrong"] if not is_correct else gate.get("consequence_if_correct", "Good call.")

    decision = SessionDecision(
        session_id=session_id,
        user_id=current_user.id,
        decision_gate_id=payload.decision_gate_id,
        chosen_option_index=payload.chosen_option_index,
        is_correct=is_correct,
        response_time_seconds=payload.response_time_seconds,
        consequence_applied=consequence,
        nist_control_ref=gate.get("nist_control_ref"),
        mitre_technique=gate.get("mitre_technique"),
    )
    db.add(decision)
    session.decisions_made += 1
    if is_correct:
        session.decisions_correct += 1
    await db.commit()

    return DecisionResult(
        decision_gate_id=payload.decision_gate_id,
        is_correct=is_correct,
        rationale=gate["rationale"],
        consequence_applied=consequence,
        nist_control_ref=gate.get("nist_control_ref", ""),
        mitre_technique=gate.get("mitre_technique", ""),
        correct_index=gate["correct_index"],
    )


@router.post("/{session_id}/complete", response_model=SessionOut)
async def complete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    assert_org_access(session, current_user)
    # Idempotent — return current state if already completed (prevents duplicate Celery tasks)
    if session.status == "completed":
        return SessionOut.model_validate(session)
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Cannot complete a '{session.status}' session")
    session.status = "completed"
    session.completed_at = datetime.utcnow()
    if session.decisions_made > 0:
        session.team_score = round((session.decisions_correct / session.decisions_made) * 100, 1)
    await db.commit()
    generate_session_debrief.delay(session_id)
    return SessionOut.model_validate(session)


@router.get("/{session_id}/debrief")
async def get_debrief(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    assert_org_access(session, current_user)
    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session not yet completed")
    if not session.debrief_report:
        # Return a 200 with a sentinel so the frontend can poll without Axios treating it as error
        return {"generating": True}
    return session.debrief_report
