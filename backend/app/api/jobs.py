"""Job submission, tracking, and result downloads."""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, update, func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    User, UserRole, Kit, Job, SampleBatch, JobStatus, KitStatus, ResultKind, ResultFile,
    FastqSource,
)
from app.auth.deps import get_current_user
from app.services import storage, notify
from app.services.storage import DEFAULT_PART_SIZE
from app.schemas.job import (
    UploadInitRequest,
    UploadInitResponse,
    MultipartCompleteRequest,
    JobCreate,
    JobConfirm,
    JobOut,
    JobSummary,
    ReanalysisRequest,
    ErrorReport,
    IngestRequest,
    ResultDownload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Files above this size go multipart; smaller ones get a single presigned PUT.
MULTIPART_THRESHOLD = DEFAULT_PART_SIZE

# A job in any of these states is finished; anything else counts as "in flight".
_TERMINAL_STATUSES = {s for s in JobStatus if s.is_terminal}


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
    req: UploadInitRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> UploadInitResponse:
    """Issue a presigned upload target. FASTQ for a kit goes under that kit's reads/ prefix;
    otherwise under the user's namespace. Server picks the key."""
    if req.kit_id is not None and req.purpose == "fastq":
        kit = db.get(Kit, req.kit_id)
        if kit is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
        if not current.is_admin and not any(u.id == current.id for u in kit.users):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
        key = f"reads/kit/{req.kit_id}/{uuid.uuid4()}/{_safe_name(req.filename)}"
    else:
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

def _resolve_target(db: Session, current: User, project_id, default_population_id, default_study_id):
    """Validate an ingestion target: population/study need a project_id, the project must be
    edit-accessible, and population/study must belong to it. Raises 422/403 on any violation."""
    if project_id is None:
        if default_population_id is not None or default_study_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "population/study require a project_id")
        return
    from app.auth.access import get_accessible_project
    from app.models import Population, Study
    project = get_accessible_project(project_id, need_edit=True, db=db, user=current)
    if default_population_id is not None:
        pop = db.get(Population, default_population_id)
        if pop is None or pop.project_id != project.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "default_population_id is not in this project")
    if default_study_id is not None:
        st = db.get(Study, default_study_id)
        if st is None or st.project_id != project.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "default_study_id is not in this project")


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

    # One job per kit at a time: block resubmission while an earlier job is still in flight.
    active_job = db.scalar(
        select(Job.id)
        .where(Job.kit_id == kit.id, Job.status.notin_(_TERMINAL_STATUSES))
        .limit(1)
    )
    if active_job is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A job for this kit is already running. Wait for it to finish before submitting again.",
        )

    valid_tags = {t.name for t in kit.tag_columns}
    seen_tags: set[str] = set()
    for b in payload.batches:
        tags = set(b.selected_tags)
        unknown = tags - valid_tags
        if valid_tags and unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"batch {b.name!r} selected unknown tag columns: {sorted(unknown)}",
            )
        # Each PP column is one physical primer plate — it may belong to only one batch.
        duplicate = tags & seen_tags
        if duplicate:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"batch {b.name!r} reuses PP columns already assigned to another batch: "
                f"{sorted(duplicate)}",
            )
        seen_tags |= tags

    # If no explicit target is given and this kit is attached to exactly one study, default the
    # ingestion target to that study (fills the Submit-page gap). The attachment already required
    # project edit rights, so we trust it and skip the per-submitter edit check below.
    auto_target = False
    if (payload.project_id is None and payload.default_population_id is None
            and payload.default_study_id is None):
        from app.models import Study, study_kits
        study_ids = db.scalars(
            select(study_kits.c.study_id).where(study_kits.c.kit_id == kit.id)
        ).all()
        if len(study_ids) == 1:
            study = db.get(Study, study_ids[0])
            payload.project_id = study.project_id
            payload.default_population_id = study.population_id
            payload.default_study_id = study.id
            auto_target = True

    # Optional project target: validate it (the auto_target path is already trusted via the
    # kit<->study attachment, which required project edit rights when it was created).
    if not auto_target:
        _resolve_target(db, current, payload.project_id,
                        payload.default_population_id, payload.default_study_id)

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
        project_id=payload.project_id,
        default_population_id=payload.default_population_id,
        default_study_id=payload.default_study_id,
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
    # Freshly uploaded reads (under this kit's prefix) become the kit's saved server reads.
    if payload.fastq_source == FastqSource.upload and \
            payload.fastq1_ref.startswith(f"reads/kit/{kit.id}/"):
        from app.services.kit_reads import set_kit_reads
        set_kit_reads(
            db, kit, fastq1_key=payload.fastq1_ref, fastq2_key=payload.fastq2_ref,
            fastq1_name=os.path.basename(payload.fastq1_ref),
            fastq2_name=os.path.basename(payload.fastq2_ref),
            uploaded_by=current.id,
        )
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


@router.post("/{public_id}/rerun", response_model=JobOut)
def rerun_job(
    public_id: str, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Re-run this job's analysis from the start (fresh head task, current pipeline image).
    Reuses the same job + inputs; re-ingestion is idempotent (find-or-create by job_id+name)."""
    job = _get_owned_job(public_id, db, current)
    if job.status != JobStatus.failed:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only a failed job can be rerun.")
    # clear the previous run's result rows (S3 objects overwrite at the same keys on the new run)
    db.execute(delete(ResultFile).where(ResultFile.job_id == job.id))
    job.status = JobStatus.queued
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    job.observed_read_count = None
    # keep reads_confirmed as-is so a previously-confirmed low-read job doesn't re-pause
    db.commit()
    db.refresh(job)
    enqueue_job(job.id)
    return job


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


@router.post("/{public_id}/request-reanalysis", status_code=status.HTTP_204_NO_CONTENT)
def request_reanalysis(
    public_id: str, payload: ReanalysisRequest,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
) -> None:
    """Ask the admins to re-enable a completed kit for another analysis, with a reason.

    A kit locks to 'analysed' after a job succeeds; only an admin can flip it back to
    'reanalyse'. This emails that request to the admins (best-effort — no DB record)."""
    job = _get_owned_job(public_id, db, current)
    if job.status != JobStatus.succeeded:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Reanalysis can only be requested for a completed (succeeded) job.",
        )
    admin_emails = list(db.scalars(select(User.email).where(User.role == UserRole.admin)))
    try:
        notify.send_reanalysis_requested(
            admin_emails, job.kit.kit_code, job.public_id, current.email, payload.reason,
        )
    except Exception:  # noqa: BLE001 — never fail the request because email is down
        logger.exception("Failed to send reanalysis-request email for job %s", job.public_id)


@router.post("/{public_id}/report-error", status_code=status.HTTP_204_NO_CONTENT)
def report_error(
    public_id: str, payload: ErrorReport,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
) -> None:
    """Email the admins about a FAILED job's error, with an optional note (best-effort; no DB record)."""
    job = _get_owned_job(public_id, db, current)
    if job.status != JobStatus.failed:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "You can only report an error for a failed job.")
    admin_emails = list(db.scalars(select(User.email).where(User.role == UserRole.admin)))
    try:
        notify.send_error_reported(
            admin_emails, job.kit.kit_code, job.public_id, current.email,
            job.error_message or "(no error message)", payload.note,
        )
    except Exception:  # noqa: BLE001 — never fail the request because email is down
        logger.exception("Failed to send error-report email for job %s", job.public_id)


_INGEST_KINDS = {
    ResultKind.consensus: "consensus_path",
    ResultKind.reference_alleles: "reference_alleles_path",
    ResultKind.genotypes: "genotypes_path",
    ResultKind.positions: "positions_path",
}


@router.post("/{public_id}/ingest")
def ingest_job(
    public_id: str, payload: IngestRequest,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Assign a completed job to a project/population/study and (re-)ingest its stored results into
    the animal/sample store — no pipeline re-run. Idempotent (samples keyed by job_id + name)."""
    from app.models import Sample
    from app.services.ingestion import ingest_job_outputs

    job = _get_owned_job(public_id, db, current)
    if job.status != JobStatus.succeeded:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only a succeeded job can be ingested into a project.")
    _resolve_target(db, current, payload.project_id,
                    payload.default_population_id, payload.default_study_id)

    job.project_id = payload.project_id
    job.default_population_id = payload.default_population_id
    job.default_study_id = payload.default_study_id
    # move any samples already ingested for this job to the new target
    db.execute(update(Sample).where(Sample.job_id == job.id).values(
        project_id=payload.project_id, population_id=payload.default_population_id,
        study_id=payload.default_study_id))

    rows = db.scalars(select(ResultFile).where(
        ResultFile.job_id == job.id, ResultFile.kind.in_(list(_INGEST_KINDS)))).all()
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for r in rows:
            dest = os.path.join(tmp, r.filename or f"{r.kind.value}.txt")
            storage.download_file(r.object_key, dest)
            paths[_INGEST_KINDS[r.kind]] = dest
        summary = ingest_job_outputs(db, job, **paths)
    db.commit()

    n_samples = db.scalar(select(func.count()).select_from(Sample).where(Sample.job_id == job.id))
    return {"samples": n_samples, "population_id": payload.default_population_id, "detail": summary}


@router.get("/{public_id}/results", response_model=list[ResultDownload])
def get_results(
    public_id: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    job = _get_owned_job(public_id, db, current)
    report_kinds = {ResultKind.html_report, ResultKind.consensus_report}
    out = []
    for rf in job.result_files:
        # HTML reports also get an inline view URL so they open in a browser tab.
        view_url = (storage.presign_get(rf.object_key, inline=True, content_type="text/html")
                    if rf.kind in report_kinds else None)
        out.append(ResultDownload(
            kind=rf.kind, filename=rf.filename,
            url=storage.presign_get(rf.object_key, rf.filename), view_url=view_url,
        ))
    return out
