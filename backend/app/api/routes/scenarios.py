import asyncio
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, Text, func, false as sa_false
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import get_db
from app.models.scenario import Scenario
from app.models.session import SimulationSession
from app.models.user import User
from app.schemas.scenario import ScenarioCreate, ScenarioOut, ScenarioDetail, ScenarioRecentOut, IndustryVertical, Difficulty
from app.core.security import get_current_user, require_admin
from app.core.stats_cache import TTLCache


class ScenarioApproveBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    initial_access_vector: Optional[str] = Field(default=None, max_length=255)
    industry_vertical: Optional[IndustryVertical] = None
    estimated_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    alert_sequence: Optional[List[Any]] = None
    decision_tree: Optional[List[Any]] = None

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("", response_model=List[ScenarioOut])
async def list_scenarios(
    industry: Optional[IndustryVertical] = Query(None),
    difficulty: Optional[Difficulty] = Query(None),
    framework: Optional[str] = Query(None, max_length=50),
    search: Optional[str] = Query(None, max_length=200),
    semantic: bool = Query(False, description="Use vector similarity search instead of keyword match"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _org_filter = (
        (Scenario.owner_org_id == current_user.organization_id)
        if current_user.organization_id
        else sa_false()
    )
    base_filter = (
        select(Scenario)
        .where(Scenario.status == "approved")
        .where((Scenario.is_private == False) | _org_filter)
        .where(Scenario.alert_sequence != None)  # noqa: E711
        .where(cast(Scenario.alert_sequence, Text) != "[]")
    )

    if industry:
        base_filter = base_filter.where(Scenario.industry_vertical == industry)
    if difficulty:
        base_filter = base_filter.where(Scenario.difficulty == difficulty)
    if framework:
        base_filter = base_filter.where(Scenario.regulatory_frameworks.any(framework))

    if search and semantic:
        # Semantic path: cosine similarity via pgvector <=> operator
        # Embedding generation is CPU-bound so we run it in a thread
        try:
            from app.pipeline.embeddings import generate_embedding
            query_vector = await asyncio.to_thread(generate_embedding, search)
            q = (
                base_filter
                .where(Scenario.embedding != None)  # noqa: E711
                .order_by(Scenario.embedding.cosine_distance(query_vector))
                .limit(limit)
                .offset(offset)
            )
        except Exception:
            # Fall back to text search if embedding fails (e.g. model not yet downloaded)
            q = (
                base_filter
                .where(Scenario.title.ilike(f"%{search}%"))
                .order_by(Scenario.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
    elif search:
        # Keyword path: fast ilike for exact / partial matches
        q = (
            base_filter
            .where(Scenario.title.ilike(f"%{search}%"))
            .order_by(Scenario.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    else:
        q = base_filter.order_by(Scenario.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(q)
    return [ScenarioOut.model_validate(s) for s in result.scalars().all()]


@router.get("/recent", response_model=List[ScenarioRecentOut])
async def list_recent_scenarios(
    limit: int = Query(10, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Live Breach Events Phase 2 — Fresh Incident Ticker. Dedicated endpoint
    # (not a query-param on list_scenarios) so its shape/caching stay
    # independent of the filterable library listing. Registered before
    # /{scenario_id} below so FastAPI doesn't try to match "recent" as a
    # scenario_id path param.
    #
    # Simpler filter than list_scenarios: no org-private carve-out, since the
    # ticker is meant to surface freshly-ingested public incidents (the kind
    # of content this feature is about), not an org's own private uploads —
    # those wouldn't read as "breaking news" to the wider audience the
    # ticker's FOMO framing targets.
    q = (
        select(Scenario)
        .where(Scenario.status == "approved")
        .where(Scenario.is_private == False)  # noqa: E712
        .order_by(Scenario.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return [ScenarioRecentOut.model_validate(s) for s in result.scalars().all()]


# ── Live Breach Events Phase 3: per-scenario public stats ───────────────────
#
# Routing decision: a SEPARATE dedicated route on this router
# (GET /scenarios/public/stats/{scenario_id}), rather than a `?scenario_id=`
# query param bolted onto GET /arena/public/stats/global-index over in
# arena.py. Reasoning: ArenaMatch.archetype_key is decoupled from
# Scenario — an ArenaMatch never carries a scenario_id at all — so a
# per-scenario stat can ONLY be computed from SimulationSession, a
# completely different table/model than the one global-index reads from.
# Cramming both into one endpoint would mean one route querying two
# unrelated tables behind one optional param, with two different response
# shapes depending on whether the param was passed. Keeping them as two
# routes on their respective routers (mirrors the same reasoning
# `GET /scenarios/recent` used in Phase 2 — a dedicated endpoint keeps
# shape/caching independent) is simpler and matches this codebase's
# existing convention of one route = one query = one shape.
#
# "Success" definition for a SimulationSession (documented here since this
# is public marketing copy, not an internal metric):
#   - Only sessions with status == "completed" are considered at all.
#   - A session only counts toward the rate (is "rated") once it has made
#     at least one graded decision (decisions_made > 0) — a completed
#     session with zero decisions has no accuracy signal, and letting it
#     divide-by-zero into the rate (or silently count as a 0%) would be
#     misleading either way.
#   - Each rated session's own decision accuracy
#     (decisions_correct / decisions_made) is compared against
#     SCENARIO_SUCCESS_THRESHOLD (0.7) to decide pass/fail — a binary
#     "successfully contained it or didn't" bucket per session, chosen to
#     deliberately mirror the Arena side's win/loss framing ("only 12% of
#     defenders worldwide contained this") rather than reporting one
#     blended average that reads like a school grade instead of a cohort
#     outcome. avg_decision_accuracy (the continuous figure) and
#     avg_team_score are still returned alongside for anyone who wants the
#     fuller picture.
#   - Never exposes a user_id, session_id, or any per-player record —
#     cohort counts/rates only.

_SCENARIO_STATS_CACHE = TTLCache(ttl_seconds=300)
SCENARIO_SUCCESS_THRESHOLD = 0.7


@router.get("/public/stats/{scenario_id}")
async def get_scenario_public_stats(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
):
    """No auth. "X% of players who played this exact incident successfully
    contained it" — the framing the founder wants, since it's tied to a
    specific ingested Scenario rather than Arena's decoupled archetype_key.
    404s for unknown, non-approved, or private scenarios alike (never
    confirms a private/draft scenario_id's existence via a public route —
    same treatment `get_public_replay` gives a non-terminal share token)."""
    cached = _SCENARIO_STATS_CACHE.get(scenario_id)
    if cached is not None:
        return cached

    scenario_result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = scenario_result.scalar_one_or_none()
    if not scenario or scenario.is_private or scenario.status != "approved":
        raise HTTPException(status_code=404, detail="Scenario not found")

    sessions_result = await db.execute(
        select(
            SimulationSession.team_score,
            SimulationSession.decisions_made,
            SimulationSession.decisions_correct,
        ).where(
            SimulationSession.scenario_id == scenario_id,
            SimulationSession.status == "completed",
        )
    )
    rows = sessions_result.all()

    total_sessions = len(rows)
    rated_rows = [r for r in rows if r.decisions_made and r.decisions_made > 0]
    accuracies = [r.decisions_correct / r.decisions_made for r in rated_rows]
    successes = [a for a in accuracies if a >= SCENARIO_SUCCESS_THRESHOLD]
    scored_values = [r.team_score for r in rows if r.team_score is not None]

    payload = {
        "scenario_id": scenario_id,
        "title": scenario.title,
        "total_sessions": total_sessions,
        "rated_sessions": len(rated_rows),
        "success_threshold": SCENARIO_SUCCESS_THRESHOLD,
        "success_rate": round(len(successes) / len(rated_rows), 4) if rated_rows else 0.0,
        "avg_decision_accuracy": round(sum(accuracies) / len(accuracies), 4) if accuracies else None,
        "avg_team_score": round(sum(scored_values) / len(scored_values), 2) if scored_values else None,
        "generated_at": datetime.utcnow().isoformat(),
        "cache_ttl_seconds": _SCENARIO_STATS_CACHE.ttl_seconds,
    }
    _SCENARIO_STATS_CACHE.set(scenario_id, payload)
    return payload


@router.get("/{scenario_id}", response_model=ScenarioDetail)
async def get_scenario(
    scenario_id: str = Path(..., max_length=36),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if scenario.is_private and scenario.owner_org_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return ScenarioDetail.model_validate(scenario)


@router.post("", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    payload: ScenarioCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    scenario = Scenario(**payload.model_dump())
    db.add(scenario)
    await db.commit()
    return ScenarioOut.model_validate(scenario)


@router.patch("/{scenario_id}/approve", response_model=ScenarioOut)
async def approve_scenario(
    scenario_id: str,
    body: Optional[ScenarioApproveBody] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if body:
        if body.title is not None:
            scenario.title = body.title
        if body.description is not None:
            scenario.description = body.description
        if body.initial_access_vector is not None:
            scenario.initial_access_vector = body.initial_access_vector
        if body.industry_vertical is not None:
            scenario.industry_vertical = body.industry_vertical
        if body.estimated_minutes is not None:
            scenario.estimated_minutes = body.estimated_minutes
        if body.alert_sequence is not None:
            scenario.alert_sequence = body.alert_sequence
        if body.decision_tree is not None:
            scenario.decision_tree = body.decision_tree
    scenario.status = "approved"
    await db.commit()
    return ScenarioOut.model_validate(scenario)


@router.patch("/{scenario_id}/reject", response_model=ScenarioOut)
async def reject_scenario(
    scenario_id: str,
    review_notes: Optional[str] = Query(None, max_length=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    scenario.status = "rejected"
    scenario.review_notes = review_notes
    await db.commit()
    return ScenarioOut.model_validate(scenario)
