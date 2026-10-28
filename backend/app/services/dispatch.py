"""Dispatch a submitted job to compute, stop it, and find out whether it is still alive.

Two modes (settings.run_mode):
  - "celery": push to Celery/Redis; a long-running worker executes it (local/VM).
  - "ecs":    launch a one-off ECS Fargate "head" task that runs the whole pipeline and exits
              (cloud-native, pay-per-use).
"""
from __future__ import annotations

import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

log = logging.getLogger(__name__)

# Container name inside the head task definition (RunTask overrides target it by name).
HEAD_CONTAINER_NAME = "head"

CELERY_HANDLE_PREFIX = "celery:"


def _ecs_client():
    return boto3.client("ecs", region_name=settings.s3_region)


def launch_head_task_ecs(job_id: int) -> str:
    """Launch the per-job ECS Fargate head task. Returns the task ARN."""
    missing = [n for n, v in (
        ("ecs_cluster", settings.ecs_cluster),
        ("head_task_def", settings.head_task_def),
        ("ecs_subnets", settings.ecs_subnet_list),
    ) if not v]
    if missing:
        raise RuntimeError(f"run_mode=ecs requires settings: {', '.join(missing)}")

    ecs = _ecs_client()
    resp = ecs.run_task(
        cluster=settings.ecs_cluster,
        taskDefinition=settings.head_task_def,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": settings.ecs_subnet_list,
                "securityGroups": [settings.ecs_security_group] if settings.ecs_security_group else [],
                "assignPublicIp": "ENABLED",  # public subnets, egress-only SG (no NAT)
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": HEAD_CONTAINER_NAME,
                    "command": ["python", "-m", "app.worker.run_job", str(job_id)],
                }
            ]
        },
    )
    tasks = resp.get("tasks", [])
    if not tasks:
        raise RuntimeError(f"ECS run_task launched no task: {resp.get('failures')}")
    return tasks[0]["taskArn"]


def stop_compute(handle: str | None, reason: str = "Stopped from STReamGT") -> bool:
    """Best-effort: kill whatever is running a job. True if we asked ECS to stop a task.

    A missing handle, or a task that has already gone, is a normal outcome rather than an error —
    the run may have died on its own, which is one of the cases a stop is used for. The job row is
    already recorded as finished by the time we get here, and the run itself would abort at its
    next checkpoint regardless, so failure here costs time, not correctness.
    """
    if not handle or handle.startswith(CELERY_HANDLE_PREFIX):
        # Local Celery runs stop at their next checkpoint; revoking needs the broker from here.
        return False
    try:
        _ecs_client().stop_task(cluster=settings.ecs_cluster, task=handle, reason=reason[:255])
        return True
    except (ClientError, BotoCoreError):
        log.exception("could not stop task %s (it may already have finished)", handle)
        return False


def describe_task_state(handle: str | None) -> str | None:
    """What ECS says about this task: its lastStatus, "GONE" if ECS has no record, else None.

    None means "don't know" — no handle, not running on ECS, or the call failed — and callers
    must treat that as "assume it is alive", because acting on a false positive now kills a
    healthy run.
    """
    if not handle or handle.startswith(CELERY_HANDLE_PREFIX) or settings.run_mode != "ecs":
        return None
    try:
        resp = _ecs_client().describe_tasks(cluster=settings.ecs_cluster, tasks=[handle])
    except (ClientError, BotoCoreError):
        log.exception("could not describe task %s", handle)
        return None
    tasks = resp.get("tasks") or []
    if tasks:
        return tasks[0].get("lastStatus")
    # ECS forgets stopped tasks after about an hour; absent means it is certainly not running.
    return "GONE" if resp.get("failures") else None


def describe_task_stop_reason(handle: str) -> str:
    """A short, human-readable account of why ECS stopped a task, for the job's error message."""
    try:
        resp = _ecs_client().describe_tasks(cluster=settings.ecs_cluster, tasks=[handle])
    except (ClientError, BotoCoreError):
        return ""
    tasks = resp.get("tasks") or []
    if not tasks:
        return ""
    code, reason = tasks[0].get("stopCode", ""), tasks[0].get("stoppedReason", "")
    return f"{code}: {reason}".strip(": ") if (code or reason) else ""
