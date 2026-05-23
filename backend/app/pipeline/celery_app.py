from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "breachreplay",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.pipeline.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "weekly-cisa-ingestion": {
            "task": "app.pipeline.tasks.ingest_cisa_advisories",
            "schedule": 604800,
        },
    },
)
