"""Beat-notification email preferences (Phase 4 retention loop).

No SendGrid calls here — unsubscribe handling and token lookup only.
Email composition lands in a later slice after beat-detection exists.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def unsubscribe_beat_notifications_by_token(
    db: AsyncSession, token: str,
) -> tuple[str, User | None]:
    """Disable beat notifications for the user owning `token`.

    Returns (status, user):
      - ("not_found", None) — unknown token
      - ("already_unsubscribed", user) — idempotent success
      - ("unsubscribed", user) — freshly opted out
    """
    user = await db.scalar(
        select(User).where(User.email_unsubscribe_token == token)
    )
    if user is None:
        return "not_found", None
    if not user.beat_notifications_enabled:
        return "already_unsubscribed", user
    user.beat_notifications_enabled = False
    await db.commit()
    await db.refresh(user)
    return "unsubscribed", user
