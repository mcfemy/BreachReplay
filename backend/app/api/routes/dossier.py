"""
Technique Dossier — per-user encounter aggregation endpoint.
Pure query-time aggregation over TechniqueEncounter (see
app.services.dossier_service); the write side lives in
app.services.action_run_store.finalize.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.core.security import get_current_user
from app.services import dossier_service

router = APIRouter(prefix="/dossier", tags=["dossier"])


@router.get("/me")
async def get_my_dossier(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await dossier_service.compute_user_dossier(db, current_user.id)
