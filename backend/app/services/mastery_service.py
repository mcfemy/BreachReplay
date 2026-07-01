"""
Competency & Mastery Engine.
Aggregates existing per-decision / per-move telemetry (SessionDecision.mitre_technique,
SessionDecision.nist_control_ref, RedTeamMove.technique_id) into a technique/control
mastery view. Pure query-time aggregation — no new source-of-truth columns.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.session import SessionDecision
from app.models.red_team import RedTeamMove, RedTeamSession
from app.core.logging import get_logger

logger = get_logger(__name__)


def _pct(correct: int, attempts: int) -> float:
    return round((correct / attempts) * 100, 1) if attempts > 0 else 0.0


async def compute_user_mastery(db: AsyncSession, user_id: str) -> dict:
    """
    Merge blue-team (SessionDecision.mitre_technique) and red-team
    (RedTeamMove.technique_id via RedTeamSession.user_id) technique history into
    a single per-technique mastery view.

    Returns: {technique_id: {attempts, correct, accuracy_pct, source: "blue"|"red"|"both"}}
    """
    # Blue-team decisions for this user, keyed by MITRE technique
    blue_result = await db.execute(
        select(SessionDecision.mitre_technique, SessionDecision.is_correct)
        .where(
            SessionDecision.user_id == user_id,
            SessionDecision.mitre_technique.isnot(None),
        )
    )
    blue_rows = blue_result.all()

    # Red-team moves for this user — RedTeamMove has no user_id, join through RedTeamSession
    red_result = await db.execute(
        select(RedTeamMove.technique_id, RedTeamMove.succeeded)
        .join(RedTeamSession, RedTeamMove.session_id == RedTeamSession.id)
        .where(
            RedTeamSession.user_id == user_id,
            RedTeamMove.technique_id.isnot(None),
        )
    )
    red_rows = red_result.all()

    mastery: dict[str, dict] = {}

    for technique, is_correct in blue_rows:
        entry = mastery.setdefault(
            technique, {"attempts": 0, "correct": 0, "accuracy_pct": 0.0, "source": "blue"}
        )
        entry["attempts"] += 1
        if is_correct:
            entry["correct"] += 1
        if entry["source"] == "red":
            entry["source"] = "both"

    for technique, succeeded in red_rows:
        entry = mastery.setdefault(
            technique, {"attempts": 0, "correct": 0, "accuracy_pct": 0.0, "source": "red"}
        )
        entry["attempts"] += 1
        if succeeded:
            entry["correct"] += 1
        if entry["source"] == "blue":
            entry["source"] = "both"

    for entry in mastery.values():
        entry["accuracy_pct"] = _pct(entry["correct"], entry["attempts"])

    return mastery


async def compute_user_nist_mastery(db: AsyncSession, user_id: str) -> dict:
    """
    Blue-team-only mastery grouped by NIST control reference (red team has no
    NIST ref today).

    Returns: {nist_control_ref: {attempts, correct, accuracy_pct}}
    """
    result = await db.execute(
        select(SessionDecision.nist_control_ref, SessionDecision.is_correct)
        .where(
            SessionDecision.user_id == user_id,
            SessionDecision.nist_control_ref.isnot(None),
        )
    )
    rows = result.all()

    mastery: dict[str, dict] = {}
    for control, is_correct in rows:
        entry = mastery.setdefault(control, {"attempts": 0, "correct": 0, "accuracy_pct": 0.0})
        entry["attempts"] += 1
        if is_correct:
            entry["correct"] += 1

    for entry in mastery.values():
        entry["accuracy_pct"] = _pct(entry["correct"], entry["attempts"])

    return mastery


def _coverage_from_exercised(exercised: list[str], scenario) -> dict:
    """Shared core: real coverage = distinct techniques actually exercised vs the
    scenario's declared technique list. No positional splitting."""
    techniques_exercised = sorted(set(exercised))
    scenario_techniques = scenario.mitre_techniques or []
    exercised_set = set(techniques_exercised)
    techniques_missed = [t for t in scenario_techniques if t not in exercised_set]

    return {
        "techniques_exercised": techniques_exercised,
        "techniques_missed": techniques_missed,
    }


async def compute_session_mitre_coverage(db: AsyncSession, session_id: str, scenario) -> dict:
    """
    Real MITRE coverage for a completed session — replaces the old positional-split
    fake logic. techniques_exercised = distinct mitre_technique values actually
    recorded on that session's SessionDecision rows; techniques_missed = the
    scenario's full technique list minus what was exercised.
    """
    result = await db.execute(
        select(SessionDecision.mitre_technique)
        .where(
            SessionDecision.session_id == session_id,
            SessionDecision.mitre_technique.isnot(None),
        )
        .distinct()
    )
    exercised = [row[0] for row in result.all()]
    return _coverage_from_exercised(exercised, scenario)


def compute_session_mitre_coverage_sync(decisions_raw: list, scenario) -> dict:
    """
    Sync-context variant for Celery tasks that already loaded SessionDecision rows
    via the sync engine (SyncSessionLocal) — avoids mixing async DB calls into a
    sync task. Same real-coverage logic as compute_session_mitre_coverage.
    """
    exercised = [d.mitre_technique for d in decisions_raw if d.mitre_technique]
    return _coverage_from_exercised(exercised, scenario)
