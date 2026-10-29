"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import (
    auth, kits, jobs, panels, users, projects, samples, consensus, matching, porting,
    control_templates,
)

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness only — dependency-free, so the container's readiness probe stays fast."""
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}


@app.get(f"{settings.api_prefix}/health", tags=["meta"])
def api_health(deep: bool = False) -> dict:
    """Reachable through CloudFront (the bare /health is not — it routes to the SPA bucket).

    With ?deep=1, check the things that are invisible until a user hits them: every S3 call once
    failed with InvalidAccessKeyId for weeks, and the pipeline parameters file was missing from
    the image, each breaking a core flow while /health still said "ok".
    """
    out: dict = {"status": "ok", "app": settings.app_name, "env": settings.environment}
    if not deep:
        return out

    checks: dict[str, str] = {}

    try:
        from sqlalchemy import text
        from app.db import engine

        with engine.connect() as conn:
            conn.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        from app.services import storage

        storage._client().head_bucket(Bucket=settings.s3_bucket)
        checks["s3"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["s3"] = f"error: {type(exc).__name__}"

    try:
        from app.services.pipeline_params import default_parameters

        checks["pipeline_parameters"] = "ok" if default_parameters() else "empty"
    except Exception as exc:  # noqa: BLE001
        checks["pipeline_parameters"] = f"error: {type(exc).__name__}"

    checks["secret_key"] = "default" if settings.secret_key == "change-me-in-prod" else "configured"
    # Its absence would silently fall back to secret_key, re-coupling kit codes to login rotation.
    checks["claim_code_key"] = "configured" if settings.claim_code_key else "missing"

    out["checks"] = checks
    out["status"] = "ok" if all(v in ("ok", "configured") for v in checks.values()) else "degraded"
    return out


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(panels.router, prefix=settings.api_prefix)
app.include_router(kits.router, prefix=settings.api_prefix)
app.include_router(control_templates.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(projects.studies_router, prefix=settings.api_prefix)
app.include_router(samples.router, prefix=settings.api_prefix)
app.include_router(consensus.router, prefix=settings.api_prefix)
app.include_router(matching.router, prefix=settings.api_prefix)
app.include_router(porting.router, prefix=settings.api_prefix)
