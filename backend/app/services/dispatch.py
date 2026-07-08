"""Dispatch a submitted job to compute.

Two modes (settings.run_mode):
  - "celery": push to Celery/Redis; a long-running worker executes it (local/VM).
  - "ecs":    launch a one-off ECS Fargate "head" task that runs the job to completion,
              then exits (cloud-native, pay-per-use). The head task drives AWS Batch.
"""
from __future__ import annotations

import boto3

from app.config import settings

# Container name inside the head task definition (RunTask overrides target it by name).
HEAD_CONTAINER_NAME = "head"


def launch_head_task_ecs(job_id: int) -> str:
    """Launch the per-job ECS Fargate head task. Returns the task ARN."""
    missing = [n for n, v in (
        ("ecs_cluster", settings.ecs_cluster),
        ("head_task_def", settings.head_task_def),
        ("ecs_subnets", settings.ecs_subnet_list),
    ) if not v]
    if missing:
        raise RuntimeError(f"run_mode=ecs requires settings: {', '.join(missing)}")

    ecs = boto3.client("ecs", region_name=settings.s3_region)
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
