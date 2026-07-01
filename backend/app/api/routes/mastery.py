"""
Competency & Mastery Engine — per-user technique/control mastery endpoint.
Pure query-time aggregation over existing SessionDecision / RedTeamMove data
(see app.services.mastery_service); no new tables.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.core.security import get_current_user
from app.services import mastery_service

router = APIRouter(prefix="/mastery", tags=["mastery"])


@router.get("/me")
async def get_my_mastery(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    technique_mastery = await mastery_service.compute_user_mastery(db, current_user.id)
    nist_mastery = await mastery_service.compute_user_nist_mastery(db, current_user.id)

    weakest_techniques = sorted(
        (
            {"technique_id": tid, **stats}
            for tid, stats in technique_mastery.items()
            if stats["attempts"] >= 1
        ),
        key=lambda t: t["accuracy_pct"],
    )[:5]

    return {
        "technique_mastery": technique_mastery,
        "nist_mastery": nist_mastery,
        "weakest_techniques": weakest_techniques,
    }
