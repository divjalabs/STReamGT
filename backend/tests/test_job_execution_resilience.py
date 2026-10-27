"""A long pipeline run must not depend on one database session staying alive.

The first real cloud run after the Neon migration died this way: the task opened a session, ran
Nextflow for seven minutes without touching the database, and the server terminated the idle
transaction. The next status write failed, the error handler's write failed too, and the task
exited — leaving the job showing "running" forever, with the kit locked behind it.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job
from app.models.enums import JobStatus, ResultKind
from app.worker import tasks
from tests.conftest import bearer
from tests.test_jobs_api import _make_kit, job_payload, no_enqueue  # noqa: F401


def _submit(client, admin_token) -> int:
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(admin_token))
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        return db.scalar(select(Job.id).where(Job.public_id == r.json()["public_id"]))


@pytest.fixture(autouse=True)
def scratch_dir(tmp_path, monkeypatch):
    """The default /scratch only exists inside the container."""
    monkeypatch.setattr(tasks.settings, "job_scratch_root", str(tmp_path))


def test_failure_is_recorded_even_when_the_session_is_dead(client, catalog, admin_token,
                                                           no_enqueue, monkeypatch):
    """Simulates the connection being dropped during the run: the job must still end `failed`."""
    job_id = _submit(client, admin_token)

    def explode(*a, **kw):
        raise RuntimeError("terminating connection due to idle-in-transaction timeout")

    # Fail at staging, the first thing after the status write.
    monkeypatch.setattr(tasks, "_stage_ref", explode)

    assert tasks.execute_job(job_id) == "failed"

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == JobStatus.failed, "a crashed run must not leave the job 'running'"
        assert job.finished_at is not None
        assert "idle-in-transaction" in (job.error_message or "")


def test_status_writes_do_not_reuse_one_session(client, catalog, admin_token, no_enqueue,
                                                monkeypatch):
    """Each status write opens and closes its own session, so nothing is held across the run."""
    opened: list[object] = []
    real_session_local = tasks.SessionLocal

    def counting_session():
        s = real_session_local()
        opened.append(s)
        return s

    monkeypatch.setattr(tasks, "SessionLocal", counting_session)
    job_id = _submit(client, admin_token)
    monkeypatch.setattr(tasks, "_stage_ref", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop")))

    tasks.execute_job(job_id)

    # One for the job lookup, then a separate one per status write (staging, failed) and the
    # recipient lookup — never a single long-lived session.
    assert len(opened) >= 3, f"expected several short sessions, saw {len(opened)}"


def test_full_run_succeeds_end_to_end(client, catalog, admin_token, no_enqueue, monkeypatch,
                                      tmp_path):
    """Walk execute_job from staging to succeeded with only the *external* calls stubbed.

    The earlier tests stopped at staging, so they never reached the code that runs after the
    session is deliberately closed — where a detached ORM object killed a real run one second in.
    This one exercises every statement in between.
    """
    job_id = _submit(client, admin_token)

    monkeypatch.setattr(tasks, "_stage_ref", lambda ref, src, dest: open(dest, "w").close())
    monkeypatch.setattr(tasks, "_stage_kit_csvs", lambda kit, d: ("primers.csv", "tags.csv"))
    monkeypatch.setattr(tasks, "_stage_batches", lambda job, d: [
        {"sample_path": "s.xlsx", "tags": "PP1-PP4"},
    ])
    monkeypatch.setattr(tasks, "build_input_tsv", lambda **kw: "kit_id\tsample_path\n")
    monkeypatch.setattr(tasks.pr, "count_fastq_reads", lambda *a, **kw: 10_000_000)

    ran: dict = {}

    def fake_run(cmd, cwd, log_path):
        ran["cmd"] = cmd          # proves the command was built before the session closed
        open(log_path, "w").close()

    monkeypatch.setattr(tasks, "_run", fake_run)

    result_file = tmp_path / "DIVJA240_genotypes.txt"
    result_file.write_text("x\n")
    monkeypatch.setattr(tasks.pr, "collect_results", lambda outdir, kit: [
        tasks.pr.CollectedResult(ResultKind.genotypes, str(result_file), result_file.name),
    ])
    monkeypatch.setattr(tasks.pr, "find_result", lambda *a, **kw: None)
    monkeypatch.setattr(tasks.storage, "upload_file", lambda src, key: None)
    monkeypatch.setattr(tasks.pr, "archive_logs", lambda *a, **kw: None)

    assert tasks.execute_job(job_id) == "succeeded", "a clean run must reach succeeded"
    assert ran["cmd"], "nextflow command was never built"

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == JobStatus.succeeded
        assert job.finished_at is not None
        assert job.kit.status.value == "analysed"
