"""Job submission, tracking, and result downloads."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, Kit, Job, SampleBatch, JobStatus, KitStatus
from app.auth.deps import get_current_user
from app.services import storage
from app.services.storage import DEFAULT_PART_SIZE
from app.schemas.job import (
    UploadInitRequest,
    UploadInitResponse,
    MultipartCompleteRequest,
    JobCreate,
    JobConfirm,
    JobOut,
    JobSummary,
    ResultDownload,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Files above this size go multipart; smaller ones get a single presigned PUT.
MULTIPART_THRESHOLD = DEFAULT_PART_SIZE


def enqueue_job(job_id: int) -> None:
    """Dispatch the job to compute. Isolated so tests can patch it.

    run_mode='ecs'    -> launch a one-off ECS Fargate head task (cloud).
    run_mode='celery' -> enqueue to Celery/Redis for a long-running worker (local/VM).
    """
    if settings.run_mode == "ecs":
        from app.services.dispatch import launch_head_task_ecs

        launch_head_task_ecs(job_id)
    else:
        from app.worker.tasks import run_pipeline

        run_pipeline.delay(job_id)


def _safe_name(name: str) -> str:
    keep = "-_.() "
    return "".join(c for c in name if c.isalnum() or c in keep).strip().replace(" ", "_") or "file"


# ---------- uploads ----------

@router.post("/uploads", response_model=UploadInitResponse)
def init_upload(
    req: UploadInitRequest, current: User = Depends(get_current_user)
) -> UploadInitResponse:
    """Issue a presigned upload target under the user's namespace. Server picks the key."""
    key = f"uploads/{current.id}/{uuid.uuid4()}/{_safe_name(req.filename)}"
    if req.size >= MULTIPART_THRESHOLD:
        mp = storage.start_multipart(key, req.size)
        return UploadInitResponse(
            key=mp.key,
            method="multipart",
            upload_id=mp.upload_id,
            part_size=mp.part_size,
            part_urls=mp.part_urls,
        )
    return UploadInitResponse(
        key=key, method="put", put_url=storage.presign_put(key, req.content_type)
    )


@router.post("/uploads/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_upload(req: MultipartCompleteRequest, _: User = Depends(get_current_user)) -> None:
    parts = [{"PartNumber": p.part_number, "ETag": p.etag} for p in req.parts]
    storage.complete_multipart(req.key, req.upload_id, parts)


# ---------- job lifecycle ----------

@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate, db: Session = Depends(get_db), current: User = Depends(get_current_user)
) -> Job:
    kit = db.get(Kit, payload.kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    # Only users granted access to the kit (or admins) may run jobs on it.
    if not current.is_admin and not any(u.id == current.id for u in kit.users):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
    # Each kit is analysed once; an admin must set it to 'reanalyse' to re-enable submission.
    if kit.status == KitStatus.analysed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This kit has already been analysed. Each kit can be analysed only once — "
            "contact an admin to re-enable analysis (reanalyse).",
        )

    valid_tags = {t.name for t in kit.tag_columns}
    for b in payload.batches:
        unknown = set(b.selected_tags) - valid_tags
        if valid_tags and unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"batch {b.name!r} selected unknown tag columns: {sorted(unknown)}",
            )

    public_id = str(uuid.uuid4())
    job = Job(
        public_id=public_id,
        user_id=current.id,
        kit_id=kit.id,
        status=JobStatus.queued,
        fastq_source=payload.fastq_source,
        fastq1_ref=payload.fastq1_ref,
        fastq2_ref=payload.fastq2_ref,
        min_identity=payload.min_identity,
        min_overlap=payload.min_overlap,
        expected_read_number=payload.expected_read_number,
        storage_prefix=f"results/{kit.kit_code}/{public_id}",
        batches=[
            SampleBatch(
                ordinal=i,
                name=b.name,
                sample_sheet_key=b.sample_sheet_key,
                sample_names_text=b.sample_names_text,
                species=b.species or kit.species,
                selected_tags=b.selected_tags,
            )
            for i, b in enumerate(payload.batches)
        ],
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    enqueue_job(job.id)
    return job


@router.get("", response_model=list[JobSummary])
def list_jobs(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return db.scalars(
        select(Job).where(Job.user_id == current.id).order_by(Job.created_at.desc())
    ).all()


def _get_owned_job(public_id: str, db: Session, current: User) -> Job:
    job = db.scalar(select(Job).where(Job.public_id == public_id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.user_id != current.id and not current.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your job")
    return job


@router.get("/{public_id}", response_model=JobOut)
def get_job(public_id: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return _get_owned_job(public_id, db, current)


@router.post("/{public_id}/confirm", response_model=JobOut)
def confirm_job(
    public_id: str, payload: JobConfirm,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Answer a job paused for low reads: run it anyway (bypassing the check) or cancel it."""
    job = _get_owned_job(public_id, db, current)
    if job.status != JobStatus.awaiting_confirmation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is not awaiting confirmation")
    if payload.proceed:
        job.reads_confirmed = True
        job.status = JobStatus.queued
        job.error_message = None
        db.commit()
        enqueue_job(job.id)
    else:
        job.status = JobStatus.failed
        job.error_message = "Cancelled by user: insufficient reads."
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    db.refresh(job)
    return job


@router.get("/{public_id}/results", response_model=list[ResultDownload])
def get_results(
    public_id: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    job = _get_owned_job(public_id, db, current)
    return [
        ResultDownload(
            kind=rf.kind,
            filename=rf.filename,
            url=storage.presign_get(rf.object_key, rf.filename),
        )
        for rf in job.result_files
    ]
