"""Notice jobs whose compute died without reporting back.

A head task can disappear mid-run — the container is killed, the database connection drops before
it can record anything, ECS fails to place the task. The job row then sits on `queued`/`running`
for ever, and because the API allows only one unfinished job per kit, that kit is locked with no
way out from the app.

This runs opportunistically whenever somebody reads a job, so it needs no scheduler and costs
nothing when nobody is looking.

Evidence before timers: ECS is asked whether the task is still there, which settles the common case
in seconds. Time limits are only a fallback for jobs with no task to ask about, and they are
deliberately generous — a false positive does not merely mislabel a live run, it stops it at its
next checkpoint (see worker/tasks.set_status).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job, JobStatus
from app.services import dispatch

log = logging.getLogger(__name__)

_TERMINAL_STATUSES = {s for s in JobStatus if s.is_terminal}

# The job page polls every few seconds; one ECS call per poll per viewer would be waste.
#
# Wall clock, deliberately, NOT time.monotonic(): on Lambda the process is frozen between
# requests and a monotonic clock does not tick while frozen, so across a hundred polls it
# advanced by a few seconds and this check was skipped every time — the first version of this
# shipped that way and never noticed a dead task.
_CHECK_INTERVAL_SECONDS = 60
_last_checked: dict[int, float] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres gives aware ones."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _fail(db: Session, job: Job, message: str) -> bool:
    """Mark the job failed, but only if it is still unfinished. True if this call did it."""
    res = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status.notin_(_TERMINAL_STATUSES))
        .values(status=JobStatus.failed, finished_at=_utcnow(), error_message=message)
    )
    db.commit()
    if res.rowcount:
        db.refresh(job)
        log.info("job %s marked failed by reconcile: %s", job.public_id, message)
        return True
    return False


def _stale_reason(job: Job) -> str | None:
    """Time-based fallback, used only when ECS cannot tell us anything."""
    now = _utcnow()
    created = _as_aware(job.created_at)
    started = _as_aware(job.started_at)

    if job.status == JobStatus.queued and started is None and created is not None:
        if now - created > timedelta(minutes=settings.job_queue_timeout_min):
            return ("The analysis never started — the compute service did not pick it up. "
                    "Nothing was run; please submit this kit again.")

    reference = started or created
    if reference is not None and now - reference > timedelta(hours=settings.job_stale_hours):
        return ("The analysis stopped reporting back and is assumed to have died. "
                "Please submit this kit again.")
    return None


def reconcile(db: Session, job: Job) -> Job:
    """Settle one job's state if its compute has gone. Returns the (possibly updated) job."""
    if job.status.is_terminal:
        return job

    last = _last_checked.get(job.id, 0.0)
    if time.time() - last < _CHECK_INTERVAL_SECONDS:
        return job
    _last_checked[job.id] = time.time()

    state = dispatch.describe_task_state(job.task_arn)
    if state in ("STOPPED", "GONE"):
        detail = dispatch.describe_task_stop_reason(job.task_arn) if state == "STOPPED" else ""
        message = "The analysis task stopped without reporting back."
        if detail:
            message += f" ({detail})"
        message += " Nothing was saved — please submit this kit again."
        _fail(db, job, message)
        return job

    if state is not None:
        return job          # ECS says it is alive; leave it alone

    reason = _stale_reason(job)
    if reason:
        _fail(db, job, reason)
    return job


def reconcile_all(db: Session, jobs: list[Job]) -> list[Job]:
    """Same, for a list — used by the jobs list so a stuck job resolves wherever it is seen."""
    for job in jobs:
        reconcile(db, job)
    return jobs
