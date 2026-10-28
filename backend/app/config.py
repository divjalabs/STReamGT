"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "STReamGT"
    environment: str = "development"
    api_prefix: str = "/api"
    # Public base URL of the frontend, used to build links in emails.
    frontend_base_url: str = "http://localhost:5173"

    # --- Security ---
    secret_key: str = "change-me-in-prod"
    access_token_expire_minutes: int = 60 * 24  # 1 day
    reset_token_expire_minutes: int = 60         # password-reset links expire in 1h
    jwt_algorithm: str = "HS256"

    # In-memory per-IP rate limiting on auth/claim endpoints (defence-in-depth).
    rate_limit_enabled: bool = True

    # --- Database ---
    # Either set database_url directly (local/dev; cloud: the full Neon URL from Parameter Store),
    # or provide db_host + db_password and let resolved_database_url assemble the URL.
    database_url: str = "postgresql+psycopg://streamgt:streamgt@localhost:5432/streamgt"
    # Open a fresh connection per session instead of pooling. Cloud: idle pooled connections
    # keep a scale-to-zero Postgres awake (and a frozen Lambda can't close them).
    db_null_pool: bool = False
    db_host: str | None = None
    db_port: int = 5432
    db_user: str = "streamgt"
    db_password: str | None = None
    db_name: str = "streamgt"

    @property
    def resolved_database_url(self) -> str:
        if self.db_host:
            return (
                f"postgresql+psycopg://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return self.database_url

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None   # defaults to redis_url
    celery_result_backend: str | None = None

    # --- Object storage (S3) ---
    s3_bucket: str = "streamgt-data"
    s3_region: str = "eu-central-1"
    s3_endpoint_url: str | None = None      # set for MinIO/localstack; None = real AWS
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    presign_expire_seconds: int = 3600

    # --- Email (SMTP / SES) ---
    smtp_host: str = "localhost"
    smtp_port: int = 1025                    # MailHog default in dev
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    email_from: str = "no-reply@streamgt.local"

    # --- Pipeline execution ---
    pipeline_dir: str = "/app/pipeline"      # where main.nf lives inside the worker/head image
    nextflow_profile: str = "docker"         # "docker" (local) | "awsbatch" (cloud)
    job_scratch_root: str = "/scratch"       # local staging dir for job workdirs

    # How a submitted job is dispatched:
    #   "celery"  -> enqueue to Celery/Redis, a long-running worker runs it (local/VM).
    #   "ecs"     -> API launches a one-off ECS Fargate "head" task per job (cloud-native).
    run_mode: str = "celery"

    # --- Giving up on a job whose compute vanished (services/job_health.py) ---
    # Only a fallback for jobs ECS can tell us nothing about, so both are deliberately generous:
    # wrongly declaring a live run dead now also stops it. Real runs take minutes, not hours.
    job_queue_timeout_min: int = 30     # queued, never started
    job_stale_hours: int = 24           # started but silent ever since

    # --- ECS (run_mode="ecs"): the per-job head task ---
    ecs_cluster: str | None = None
    head_task_def: str | None = None         # task definition family[:revision]
    ecs_subnets: str | None = None           # comma-separated public subnet ids
    ecs_security_group: str | None = None    # the API/head security group id

    # --- AWS Batch (nextflow_profile="awsbatch") ---
    nxf_batch_queue: str = "streamgt-queue"
    obitools_image: str | None = None        # ECR URI of the OBITools image
    nxf_work_dir: str | None = None          # s3://<bucket>/work for Nextflow's Batch work-dir

    @property
    def ecs_subnet_list(self) -> list[str]:
        return [s.strip() for s in (self.ecs_subnets or "").split(",") if s.strip()]

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


def _load_ssm_parameters() -> None:
    """Cloud (Lambda): export every parameter under SSM_PARAMETER_PATH (e.g. /streamgt/) as an env
    var named by its last path segment, e.g. /streamgt/SECRET_KEY -> SECRET_KEY. Explicit env vars
    win. ECS tasks get the same parameters injected natively via the task definition instead."""
    path = os.environ.get("SSM_PARAMETER_PATH")
    if not path:
        return
    import boto3

    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
    for page in ssm.get_paginator("get_parameters_by_path").paginate(Path=path, WithDecryption=True):
        for p in page["Parameters"]:
            os.environ.setdefault(p["Name"].rsplit("/", 1)[-1], p["Value"])


@lru_cache
def get_settings() -> Settings:
    _load_ssm_parameters()
    return Settings()


settings = get_settings()
