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
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}


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
