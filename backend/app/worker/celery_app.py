"""Celery application. Tasks are defined in app.worker.tasks."""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "streamgt",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,          # a crashed worker re-queues the job
    worker_prefetch_multiplier=1, # one long job at a time per worker process
    result_expires=60 * 60 * 24 * 7,
)
