"""ECS head-task entrypoint: run a single genotyping job synchronously (no Celery).

The API launches an ECS Fargate task with this as its command when run_mode="ecs":
    python -m app.worker.run_job <job_id>
(the job id may also be supplied via the JOB_ID env var). The task exits 0 on success,
1 on failure — which ECS records as the task's exit code.
"""
from __future__ import annotations

import os
import sys

from app.worker.tasks import execute_job


def main() -> None:
    job_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JOB_ID")
    if not job_id:
        print("usage: python -m app.worker.run_job <job_id>  (or set JOB_ID)", file=sys.stderr)
        raise SystemExit(2)
    result = execute_job(int(job_id))
    print(f"job {job_id}: {result}")
    raise SystemExit(0 if result == "succeeded" else 1)


if __name__ == "__main__":
    main()
