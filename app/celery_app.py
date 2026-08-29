from celery import Celery  # type: ignore[import-untyped]

from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "ai_intelligent_site",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "worker-heartbeat": {
            "task": "monitor.worker_heartbeat",
            "schedule": 30.0,
        },
        "monitor-health": {
            "task": "monitor.health",
            "schedule": 60.0,
        },
    },
)
