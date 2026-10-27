"""Celery application. Tasks are defined in app.worker.tasks."""
from __future__ import annotations

import os

from celery import Celery

from app.config import settings

celery_app = Celery(
    "streamgt",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.worker.tasks"],
)

# Dev/test convenience: run tasks inline (no broker/worker) when CELERY_TASK_ALWAYS_EAGER is set.
_eager = os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("1", "true", "yes")

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,          # a crashed worker re-queues the job
    worker_prefetch_multiplier=1, # one long job at a time per worker process
    result_expires=60 * 60 * 24 * 7,
    task_always_eager=_eager,
    task_eager_propagates=_eager,
)
