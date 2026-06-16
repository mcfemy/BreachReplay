"""
Certification endpoints — issue, list, and publicly verify credentials.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.cert_service import (
    CERTIFICATIONS,
    check_and_award_certs,
    get_user_certs,
    verify_cert_by_token,
)

router = APIRouter(prefix="/certs", tags=["certifications"])


@router.get("/catalogue")
async def get_catalogue():
    """All possible certifications — public."""
    return [
        {"key": k, **v}
        for k, v in CERTIFICATIONS.items()
    ]


@router.get("/mine")
async def get_my_certs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check for new certifications and return all earned certs."""
    newly_issued = await check_and_award_certs(db, current_user.id)
    certs = await get_user_certs(db, current_user.id)
    return {"certs": certs, "newly_issued": newly_issued}


@router.post("/check")
async def trigger_cert_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explicitly re-run all eligibility checks and issue any earned certs."""
    newly_issued = await check_and_award_certs(db, current_user.id)
    certs = await get_user_certs(db, current_user.id)
    return {"newly_issued": newly_issued, "total_certs": len(certs), "certs": certs}


@router.get("/verify/{token}")
async def verify_certificate(token: str, db: AsyncSession = Depends(get_db)):
    """Public certificate verification — no auth required."""
    result = await verify_cert_by_token(db, token)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found or invalid")
    return result
