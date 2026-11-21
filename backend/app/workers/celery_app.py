from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging()
celery_app = Celery("pdf_to_word_pro", broker=settings.redis_url, include=["app.workers.tasks", "app.benchmark.tasks"])
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.job_timeout_seconds + 20,
    task_soft_time_limit=settings.job_timeout_seconds,
    worker_prefetch_multiplier=1,
    task_default_queue="pdfpro",
    broker_transport_options={"visibility_timeout": settings.job_timeout_seconds * 2 + 60},
    broker_connection_retry_on_startup=True,
    worker_redirect_stdouts=False,
    beat_schedule={
        "retention-cleanup": {"task": "pdfpro.cleanup", "schedule": 60.0},
        "benchmark-recovery": {"task": "pdfpro.benchmark.recover", "schedule": 60.0,
                               "options": {"queue": "pdfpro.benchmark"}},
    },
)
