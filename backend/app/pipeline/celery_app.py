from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "breachreplay",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.pipeline.tasks"],
)

_WEEK = 604800   # seconds
_MONTH = 2592000  # 30 days in seconds

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # RedBeat stores "when did each periodic task last run" in Redis instead
    # of a local file inside the beat container. Redis is the one process in
    # this stack that survives every deploy (db/redis aren't recreated, only
    # backend/beat/worker are) — without this, every deploy silently resets
    # the weekly/monthly ingestion countdown clocks.
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=settings.REDIS_URL,
    beat_schedule={
        # CISA AA-prefixed advisories — weekly
        "weekly-cisa-ingestion": {
            "task": "app.pipeline.tasks.ingest_cisa_advisories",
            "schedule": _WEEK,
            "kwargs": {"limit": 10},
        },
        # SEC EDGAR 8-K cybersecurity disclosures — weekly (last 30 days window)
        "weekly-sec-ingestion": {
            "task": "app.pipeline.tasks.ingest_sec_8k_filings",
            "schedule": _WEEK,
            "kwargs": {"days_back": 30, "limit": 5},
        },
        # HHS OCR Breach Portal CSV — monthly (large breaches only)
        "monthly-hhs-ingestion": {
            "task": "app.pipeline.tasks.ingest_hhs_breaches",
            "schedule": _MONTH,
            "kwargs": {"min_individuals": 10000, "limit": 5},
        },
        # Krebs on Security + SANS ISC RSS feeds — weekly
        "weekly-rss-ingestion": {
            "task": "app.pipeline.tasks.ingest_rss_feeds",
            "schedule": _WEEK,
            "kwargs": {"limit_per_feed": 3},
        },
        # Backfill embeddings for any scenarios missing them — daily, fast no-op when all are covered
        "daily-embedding-backfill": {
            "task": "app.pipeline.tasks.backfill_scenario_embeddings",
            "schedule": 86400,  # 24 hours
        },
        # Post a random scenario snippet to Slack every week
        "weekly-slack-snippet": {
            "task": "app.pipeline.tasks.send_weekly_slack_snippet",
            "schedule": _WEEK,
        },
    },
)
