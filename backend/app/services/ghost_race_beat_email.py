"""Beat-notification email delivery for ghost_race_beats rows (Phase 4).

Trigger pattern matches sessions.complete_session's debrief-ready email:
`asyncio.create_task` + `asyncio.to_thread` on the request/finalize path,
not Celery (Celery is used for debrief *generation*, not the email itself).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update

from app.core.config import settings
from app.db.session import SyncSessionLocal
from app.models.action_run import ActionRun
from app.models.ghost_race_beat import GhostRaceBeat
from app.models.scenario import Scenario
from app.models.user import User
from app.services.email_service import send_ghost_race_beat_email

logger = logging.getLogger(__name__)

# Per-owner backstop beyond per-row dedupe — a viral shared run can rack up
# many beats in one day; cap actual SendGrid deliveries, not skipped rows.
BEAT_EMAIL_DAILY_CAP = 3


def beat_unsubscribe_url(token: str) -> str:
    return f"{settings.FRONTEND_URL}/api/v1/unsubscribe?token={token}"


def _utc_day_start(when: datetime) -> datetime:
    return when.replace(hour=0, minute=0, second=0, microsecond=0)


def _racer_label(user: Optional[User]) -> str:
    if user and user.full_name:
        return user.full_name
    return "Another analyst"


def _format_seconds(seconds: int) -> str:
    minutes, secs = divmod(max(0, seconds), 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _delivered_today_count(db, owner_user_id: str, now: datetime) -> int:
    day_start = _utc_day_start(now)
    return db.scalar(
        select(func.count())
        .select_from(GhostRaceBeat)
        .where(
            GhostRaceBeat.ghost_owner_user_id == owner_user_id,
            GhostRaceBeat.email_delivered_at.is_not(None),
            GhostRaceBeat.email_delivered_at >= day_start,
        )
    ) or 0


def process_beat_notification_email(beat_id: str) -> str:
    """Claim a beat row and send/skip its notification email exactly once."""
    now = datetime.utcnow()

    with SyncSessionLocal() as db:
        claim = db.execute(
            update(GhostRaceBeat)
            .where(
                GhostRaceBeat.id == beat_id,
                GhostRaceBeat.email_sent_at.is_(None),
            )
            .values(email_sent_at=now)
        )
        if claim.rowcount == 0:
            db.rollback()
            return "already_processed"

        beat = db.get(GhostRaceBeat, beat_id)
        if beat is None:
            db.commit()
            return "not_found"

        if not beat.ghost_owner_user_id:
            db.commit()
            return "skipped_no_owner"

        owner = db.get(User, beat.ghost_owner_user_id)
        if owner is None or not owner.email:
            db.commit()
            return "skipped_no_recipient"

        if not beat.ghost_owner_beat_notifications_enabled:
            db.commit()
            return "skipped_opt_out"

        if _delivered_today_count(db, owner.id, now) >= BEAT_EMAIL_DAILY_CAP:
            db.commit()
            return "skipped_daily_cap"

        racer = db.get(User, beat.racer_user_id)
        ghost_run = db.get(ActionRun, beat.ghost_action_run_id)
        scenario_title = "your scenario"
        if ghost_run is not None:
            scenario = db.get(Scenario, ghost_run.scenario_id)
            if scenario and scenario.title:
                scenario_title = scenario.title

        seconds_faster = beat.ghost_containment_seconds - beat.racer_containment_seconds
        delivered = send_ghost_race_beat_email(
            owner.email,
            racer_label=_racer_label(racer),
            scenario_title=scenario_title,
            seconds_faster=seconds_faster,
            racer_time_label=_format_seconds(beat.racer_containment_seconds),
            ghost_time_label=_format_seconds(beat.ghost_containment_seconds),
            unsubscribe_url=beat_unsubscribe_url(owner.email_unsubscribe_token),
        )
        if delivered:
            beat.email_delivered_at = now
        db.commit()
        return "sent" if delivered else "send_failed"


def schedule_beat_notification_email(beat_id: str) -> None:
    """Fire-and-forget on the running event loop (matches debrief email)."""

    async def _send_safe() -> None:
        try:
            await asyncio.to_thread(process_beat_notification_email, beat_id)
        except Exception:
            logger.exception("Failed to process beat notification email beat_id=%s", beat_id)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        process_beat_notification_email(beat_id)
        return

    asyncio.create_task(_send_safe())
