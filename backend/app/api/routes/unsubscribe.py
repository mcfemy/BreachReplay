"""Public unsubscribe endpoint for beat-notification emails (no auth)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.user_email_prefs import unsubscribe_beat_notifications_by_token

router = APIRouter(tags=["unsubscribe"])


@router.get("/unsubscribe")
async def unsubscribe_beat_notifications(
    token: str = Query(..., min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    """One-click opt-out from beat-notification emails.

    Email links will point here with the user's stable
    `email_unsubscribe_token`. No session required.
    """
    status, user = await unsubscribe_beat_notifications_by_token(db, token)
    if status == "not_found":
        raise HTTPException(status_code=404, detail="Unsubscribe link not found")
    if status == "already_unsubscribed":
        return {
            "message": "You are already unsubscribed from beat-notification emails.",
            "beat_notifications_enabled": False,
        }
    return {
        "message": "You have been unsubscribed from beat-notification emails.",
        "beat_notifications_enabled": user.beat_notifications_enabled if user else False,
    }
