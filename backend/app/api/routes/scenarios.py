import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, Text, func, false as sa_false
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import get_db
from app.models.scenario import Scenario
from app.models.user import User
from app.schemas.scenario import ScenarioCreate, ScenarioOut, ScenarioDetail, IndustryVertical, Difficulty
from app.core.security import get_current_user, require_admin


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
