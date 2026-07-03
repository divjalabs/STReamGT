"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

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
    jwt_algorithm: str = "HS256"

    # --- Database ---
    database_url: str = "postgresql+psycopg://streamgt:streamgt@localhost:5432/streamgt"

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
    pipeline_dir: str = "/app/pipeline"      # where main.nf lives inside the worker image
    nextflow_profile: str = "docker"
    job_scratch_root: str = "/scratch"       # local staging dir for job workdirs

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
