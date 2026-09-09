from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "askmydocs",
    broker=settings.REDIS_URL,          # where tasks are queued
    backend=settings.REDIS_URL,         # where results are stored
    include=["app.worker.tasks"],       # modules the worker must import
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],            # never accept pickle — it can execute code
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,            # gives us a STARTED state, not just PENDING
    result_expires=3600,                # results self-delete after 1 hour
    broker_connection_retry_on_startup=True,
)