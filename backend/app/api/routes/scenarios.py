from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from app.db.session import get_db
from app.models.scenario import Scenario
from app.models.user import User
from app.schemas.scenario import ScenarioCreate, ScenarioOut, ScenarioDetail, IndustryVertical, Difficulty
from app.core.security import get_current_user, require_admin

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("", response_model=List[ScenarioOut])
async def list_scenarios(
    industry: Optional[IndustryVertical] = Query(None),
    difficulty: Optional[Difficulty] = Query(None),
    framework: Optional[str] = Query(None, max_length=50),
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Scenario).where(Scenario.status == "approved").where(
        (Scenario.is_private == False) | (Scenario.owner_org_id == current_user.organization_id)
    )
    if industry:
        q = q.where(Scenario.industry_vertical == industry)
    if difficulty:
        q = q.where(Scenario.difficulty == difficulty)
    if framework:
        q = q.where(Scenario.regulatory_frameworks.any(framework))
    if search:
        q = q.where(Scenario.title.ilike(f"%{search}%"))
    q = q.order_by(Scenario.created_at.desc()).limit(limit).offset(offset)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
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
