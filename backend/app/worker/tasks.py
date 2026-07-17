"""Celery task: run one genotyping job end-to-end.

Flow (status transitions in parentheses):
  (staging)   download FASTQ + kit CSVs + sample sheets from S3, build input.tsv
  (running)   nextflow run main.nf -profile <docker>  in the job scratch dir
  (rendering) render Genotype_stat.Rmd -> HTML
  (uploading) push results/ + reports/ + report.html to S3, record ResultFile rows
  (succeeded / failed)  update status, email the user
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone

from app.config import settings
from app.db import SessionLocal
from app.models import Job, ResultFile, ResultKind, JobStatus, FastqSource, KitStatus
from app.services import storage, notify
from app.services.samplesheet import build_input_tsv, BatchRow
from app.worker.celery_app import celery_app
from app.worker import pipeline_run as pr

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stage_ref(ref: str, source: FastqSource, dest: str) -> None:
    """Materialize a FASTQ ref (S3 key / server path / URL) to a local file."""
    if source == FastqSource.link:
        urllib.request.urlretrieve(ref, dest)
    elif source == FastqSource.server and os.path.isabs(ref) and os.path.exists(ref):
        shutil.copy(ref, dest)
    else:  # upload, or server key held in the bucket
        storage.download_file(ref, dest)


def _stage_kit_csvs(kit, inputs_dir: str) -> tuple[str, str]:
    """Return (primers_csv_path, tags_csv_path), staged locally.

    tags CSV must come from S3 (positional tag values can't be reconstructed from the DB).
    primers CSV is taken from S3 if present, else reconstructed from the Primer rows.
    """
    tags_path = os.path.join(inputs_dir, "tags.csv")
    if not kit.tags_csv_key:
        raise RuntimeError(f"kit {kit.kit_code} has no tags CSV stored; cannot run")
    storage.download_file(kit.tags_csv_key, tags_path)

    primers_path = os.path.join(inputs_dir, "primers.csv")
    if kit.primers_csv_key:
        storage.download_file(kit.primers_csv_key, primers_path)
    else:
        _write_primers_csv(kit, primers_path)
    return primers_path, tags_path


def _write_primers_csv(kit, path: str) -> None:
    import csv

    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["locus", "primerF", "primerR", "type", "motif", "sequence"])
        for p in kit.primers:
            w.writerow([p.locus, p.primer_f or "", p.primer_r or "",
                        p.type.value, p.motif or "", p.sequence or ""])


def _stage_batches(job, inputs_dir: str) -> list[BatchRow]:
    rows: list[BatchRow] = []
    for b in job.batches:
        xlsx = os.path.join(inputs_dir, f"{b.name}_{b.id}.xlsx")
        if b.sample_sheet_key:
            storage.download_file(b.sample_sheet_key, xlsx)
        elif b.sample_names_text:
            pr.write_sample_xlsx(pr.samples_text_to_rows(b.sample_names_text), xlsx)
        else:
            raise RuntimeError(f"batch {b.name} has no sample sheet or pasted samples")
        rows.append(BatchRow(sample_path=xlsx, selected_tags=list(b.selected_tags)))
    return rows


def _run(cmd: list[str], cwd: str, log_path: str) -> None:
    with open(log_path, "ab") as log:
        log.write(f"\n$ {' '.join(cmd)}\n".encode())
        log.flush()
        proc = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = _tail(log_path)
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd[:3])}\n{tail}")


def _tail(path: str, n: int = 40) -> str:
    try:
        with open(path, "r", errors="replace") as fh:
            return "".join(fh.readlines()[-n:])
    except OSError:
        return ""


@celery_app.task(name="run_pipeline", bind=True)
def run_pipeline(self, job_id: int) -> str:
    """Celery entrypoint (run_mode='celery', local/VM). Delegates to execute_job."""
    return execute_job(job_id)


def _prepare_awsbatch_env() -> None:
    """Export the values the awsbatch Nextflow profile reads (see pipeline/nextflow.config),
    so the Nextflow subprocess picks them up whether run on a VM worker or an ECS head task."""
    if settings.nextflow_profile != "awsbatch":
        return
    mapping = {
        "NXF_BATCH_QUEUE": settings.nxf_batch_queue,
        "OBITOOLS_IMAGE": settings.obitools_image,
        "NXF_WORK": settings.nxf_work_dir,
        "AWS_REGION": settings.s3_region,
    }
    for k, v in mapping.items():
        if v:
            os.environ[k] = v


def execute_job(job_id: int) -> str:
    """Run one genotyping job end-to-end. Called by the Celery task (local) or the ECS head
    entrypoint `python -m app.worker.run_job <id>` (cloud). Profile-agnostic: runs
    `nextflow -profile <settings.nextflow_profile>` — 'docker' locally, 'awsbatch' in cloud
    (Nextflow stages the staged inputs to the S3 work-dir and farms each process to Batch)."""
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        return "job-not-found"
    kit = job.kit
    scratch = os.path.join(settings.job_scratch_root, job.public_id)
    inputs_dir = os.path.join(scratch, "inputs")
    log_path = os.path.join(scratch, "run.log")

    def set_status(status: JobStatus, **fields) -> None:
        job.status = status
        for k, v in fields.items():
            setattr(job, k, v)
        db.commit()

    try:
        os.makedirs(inputs_dir, exist_ok=True)
        set_status(JobStatus.staging, started_at=_now())

        # 1. Stage inputs.
        fq1 = os.path.join(inputs_dir, "reads_1.fastq.gz")
        fq2 = os.path.join(inputs_dir, "reads_2.fastq.gz")
        _stage_ref(job.fastq1_ref, job.fastq_source, fq1)
        _stage_ref(job.fastq2_ref, job.fastq_source, fq2)

        # Pre-flight: if the FASTQ has fewer reads than expected, pause for the user to confirm
        # rather than burning a full pipeline run. Runs before Nextflow ever starts.
        if job.expected_read_number and not job.reads_confirmed:
            observed = pr.count_fastq_reads(fq1, stop_at=job.expected_read_number)
            if observed < job.expected_read_number:
                set_status(
                    JobStatus.awaiting_confirmation,
                    observed_read_count=observed,
                    error_message=(f"FASTQ has {observed} reads, below the expected "
                                   f"{job.expected_read_number}. Awaiting confirmation to run."),
                )
                _safe_notify(notify.send_job_needs_confirmation, job.user.email,
                             kit.kit_code, job.public_id, observed, job.expected_read_number)
                return "awaiting_confirmation"

        primers_csv, tags_csv = _stage_kit_csvs(kit, inputs_dir)
        batch_rows = _stage_batches(job, inputs_dir)

        # 2. Build input.tsv.
        tsv = build_input_tsv(
            kit_id=kit.kit_code, tags_path=tags_csv, primers_path=primers_csv,
            fastq1_path=fq1, fastq2_path=fq2, batches=batch_rows,
        )
        input_tsv = os.path.join(scratch, "input.tsv")
        with open(input_tsv, "w") as fh:
            fh.write(tsv)

        # 3. Run Nextflow (outputs land at {scratch}/{kit_code}/...; the pipeline's REPORT
        #    process generates the HTML reports, so no separate render step here).
        set_status(JobStatus.running)
        _prepare_awsbatch_env()  # no-op unless nextflow_profile == "awsbatch"
        _run(
            pr.build_nextflow_cmd(
                pipeline_dir=settings.pipeline_dir, input_tsv=input_tsv, run_dir=scratch,
                profile=settings.nextflow_profile,
                min_identity=job.min_identity, min_overlap=job.min_overlap,
                expected_read_number=job.expected_read_number,
            ),
            cwd=scratch, log_path=log_path,
        )

        results = pr.collect_results(scratch, kit.kit_code)
        if not results:
            raise RuntimeError("pipeline produced no result files")

        # 4. Upload results to S3 and record them (HTML reports are collected by suffix).
        set_status(JobStatus.uploading)
        prefix = job.storage_prefix or f"results/{kit.kit_code}/{job.public_id}"
        for r in results:
            key = f"{prefix}/{r.filename}"
            storage.upload_file(r.path, key)
            db.add(ResultFile(job_id=job.id, kind=r.kind, object_key=key,
                              filename=r.filename, size_bytes=os.path.getsize(r.path)))
        db.commit()

        # 4b. Ingest structured genotype data into the project store (best-effort; a parsing
        #     failure must not fail an otherwise-successful genotyping job).
        if job.project_id:
            try:
                from app.services.ingestion import ingest_job_outputs
                summary = ingest_job_outputs(
                    db, job,
                    consensus_path=pr.find_result(results, ResultKind.consensus),
                    reference_alleles_path=pr.find_result(results, ResultKind.reference_alleles),
                    genotypes_path=pr.find_result(results, ResultKind.genotypes),
                    positions_path=pr.find_result(results, ResultKind.positions),
                )
                db.commit()
                log.info("ingested job %s into project %s: %s", job.public_id, job.project_id, summary)
            except Exception as ing_exc:  # noqa: BLE001
                db.rollback()
                log.exception("ingestion failed for job %s: %s", job.public_id, ing_exc)

        kit.status = KitStatus.analysed  # a successful job marks the kit analysed
        set_status(JobStatus.succeeded, finished_at=_now())
        _safe_notify(notify.send_job_succeeded, job.user.email, kit.kit_code, job.public_id)
        return "succeeded"

    except Exception as exc:  # noqa: BLE001 — record any failure on the job
        set_status(JobStatus.failed, finished_at=_now(), error_message=str(exc)[:4000])
        _safe_notify(notify.send_job_failed, job.user.email, kit.kit_code, job.public_id, str(exc)[:500])
        return "failed"
    finally:
        db.close()
        # Keep scratch on failure for debugging; clean on success.
        if job.status == JobStatus.succeeded:
            shutil.rmtree(scratch, ignore_errors=True)


def _safe_notify(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 — email must never crash the task
        # Best-effort: a failed email must not fail the job, but it must be visible.
        # Logs to CloudWatch (/ecs/streamgt-head, /ecs/streamgt-api) for diagnosis.
        log.exception("notification %s failed", getattr(fn, "__name__", fn))
