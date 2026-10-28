"""Stopping a running analysis, and noticing one whose compute died.

Before this, a user who spotted a mistake just after submitting had no way out: no stop control,
and a run that completed locked the kit as `analysed` until an admin unlocked it. The same gap let
a dead task keep a kit locked for ever.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, JobStatus, Kit, KitStatus
from tests.conftest import bearer, register, user_id
from tests.test_jobs_api import _make_kit, job_payload, _set_status, no_enqueue  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_health_checks():
    """The reconciler throttles its ECS calls per job id; ids repeat across tests."""
    from app.services import job_health

    job_health._last_checked.clear()
    yield
    job_health._last_checked.clear()


@pytest.fixture()
def no_compute_stop(monkeypatch):
    """Record which task the API tried to kill, instead of calling AWS."""
    stopped: list[str | None] = []
    monkeypatch.setattr("app.services.dispatch.stop_compute",
                        lambda handle, reason="": stopped.append(handle) or True)
    return stopped


def _submit(client, token, kit_id) -> str:
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(token))
    assert r.status_code == 201, r.text
    return r.json()["public_id"]


def _job_row(public_id) -> Job:
    with SessionLocal() as db:
        return db.scalar(select(Job).where(Job.public_id == public_id))


# --- Stopping ---------------------------------------------------------------------------

def test_stop_frees_the_kit_for_a_new_submission(client, catalog, admin_token, no_compute_stop):
    """The whole point: stop a mistake, submit again straight away, no admin involved."""
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)

    r = client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"
    assert "Stopped by you" in r.json()["error_message"]
    assert r.json()["finished_at"]

    # The kit was never analysed, so it accepts a new run immediately.
    again = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(admin_token))
    assert again.status_code == 201, "a stopped job must not keep the kit locked"


def test_stop_kills_the_recorded_task(client, catalog, admin_token, monkeypatch, no_compute_stop):
    """The task id recorded at dispatch is what gets stopped."""
    arn = "arn:aws:ecs:eu-central-1:123:task/streamgt/deadbeef"
    monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: arn)

    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    assert _job_row(pub).task_arn == arn, "dispatch must record the task handle"

    client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token))
    assert no_compute_stop == [arn]


def test_stop_succeeds_even_when_the_task_cannot_be_killed(client, catalog, admin_token,
                                                           monkeypatch):
    """Recording the stop matters more than the kill: the run aborts at its next checkpoint."""
    def boom(handle, reason=""):
        raise RuntimeError("AWS said no")

    monkeypatch.setattr("app.services.dispatch.stop_compute", boom)
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)

    with pytest.raises(RuntimeError):
        client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token))
    assert _job_row(pub).status == JobStatus.failed, "the stop must be recorded before the kill"


def test_stop_refused_while_saving_results(client, catalog, admin_token, no_compute_stop):
    """`uploading` writes results, ingests genotypes and locks the kit — too late to cut in half."""
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    _set_status(pub, "uploading")

    r = client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token))
    assert r.status_code == 409
    assert "too late" in r.json()["detail"].lower()
    assert _job_row(pub).status == JobStatus.uploading, "the job must be left alone"


def test_stop_refused_once_finished(client, catalog, admin_token, no_compute_stop):
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    _set_status(pub, "succeeded")
    assert client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token)).status_code == 409


def test_stop_does_not_overwrite_an_earlier_failure(client, catalog, admin_token, no_compute_stop):
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.public_id == pub))
        job.status = JobStatus.failed
        job.error_message = "pipeline exploded"
        db.commit()

    assert client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token)).status_code == 409
    assert _job_row(pub).error_message == "pipeline exploded"


def test_only_the_owner_or_an_admin_may_stop(client, catalog, admin_token, user_token,
                                             no_compute_stop):
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("user@x.com")])
    pub = _submit(client, user_token, kit_id)

    other = register(client, "someone-else@lab.org")
    assert client.post(f"/api/jobs/{pub}/stop", headers=bearer(other)).status_code == 403

    r = client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token))
    assert r.status_code == 200
    assert "Stopped by an admin" in r.json()["error_message"], "say who stopped it"


def test_a_stopped_job_can_be_rerun(client, catalog, admin_token, no_compute_stop, no_enqueue):
    """A stop records `failed`, so the existing rerun path works unchanged."""
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    client.post(f"/api/jobs/{pub}/stop", headers=bearer(admin_token))

    r = client.post(f"/api/jobs/{pub}/rerun", headers=bearer(admin_token))
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert r.json()["error_message"] is None


# --- A launch that fails must not leave a ghost ------------------------------------------

@pytest.mark.parametrize("second_call", [False, True])
def test_dispatch_failure_marks_the_job_failed(client, catalog, admin_token, monkeypatch,
                                               second_call):
    """A job committed as `queued` with nothing running locked its kit for ever."""
    def refuse(job_id):
        raise RuntimeError("ECS capacity")

    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    monkeypatch.setattr("app.api.jobs.enqueue_job", refuse)

    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(admin_token))
    assert r.status_code == 503
    assert "try again" in r.json()["detail"].lower()

    with SessionLocal() as db:
        job = db.scalars(select(Job).order_by(Job.id.desc())).first()
        assert job.status == JobStatus.failed, "a job that never started must not stay queued"
        assert "Could not start" in job.error_message

    if second_call:
        # And the kit is immediately usable again.
        monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: None)
        assert client.post("/api/jobs", json=job_payload(kit_id),
                           headers=bearer(admin_token)).status_code == 201


# --- Noticing a dead task -----------------------------------------------------------------

def test_a_dead_task_is_noticed_when_the_job_is_read(client, catalog, admin_token, monkeypatch):
    """The failure mode hit twice in production: the task dies, the job says `running` for ever."""
    arn = "arn:aws:ecs:eu-central-1:123:task/streamgt/gone"
    monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: arn)
    monkeypatch.setattr("app.services.job_health.dispatch.describe_task_state",
                        lambda handle: "STOPPED")
    monkeypatch.setattr("app.services.job_health.dispatch.describe_task_stop_reason",
                        lambda handle: "TaskFailedToStart: out of memory")

    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    _set_status(pub, "running")

    r = client.get(f"/api/jobs/{pub}", headers=bearer(admin_token))
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert "out of memory" in r.json()["error_message"], "say what ECS reported"


def test_a_live_task_is_left_alone(client, catalog, admin_token, monkeypatch):
    monkeypatch.setattr("app.api.jobs.enqueue_job",
                        lambda job_id: "arn:aws:ecs:eu-central-1:123:task/streamgt/alive")
    monkeypatch.setattr("app.services.job_health.dispatch.describe_task_state",
                        lambda handle: "RUNNING")

    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    _set_status(pub, "running")

    r = client.get(f"/api/jobs/{pub}", headers=bearer(admin_token))
    assert r.json()["status"] == "running", "a healthy run must never be declared dead"


def test_a_job_that_never_started_is_swept(client, catalog, admin_token, monkeypatch):
    """No task to ask about — fall back to time."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr("app.services.job_health.dispatch.describe_task_state", lambda h: None)
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)

    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.public_id == pub))
        job.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
        db.commit()

    r = client.get(f"/api/jobs/{pub}", headers=bearer(admin_token))
    assert r.json()["status"] == "failed"
    assert "never started" in r.json()["error_message"]


def test_a_fresh_queued_job_is_not_swept(client, catalog, admin_token, monkeypatch):
    monkeypatch.setattr("app.services.job_health.dispatch.describe_task_state", lambda h: None)
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)

    r = client.get(f"/api/jobs/{pub}", headers=bearer(admin_token))
    assert r.json()["status"] == "queued", "a job submitted moments ago is not stale"


def test_sweeping_never_unlocks_a_kit(client, catalog, admin_token, monkeypatch):
    """A job that died while saving results may legitimately have locked the kit."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr("app.services.job_health.dispatch.describe_task_state", lambda h: None)
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    pub = _submit(client, admin_token, kit_id)
    _set_status(pub, "uploading")

    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.public_id == pub))
        job.started_at = datetime.now(timezone.utc) - timedelta(days=3)
        db.get(Kit, kit_id).status = KitStatus.analysed
        db.commit()

    client.get(f"/api/jobs/{pub}", headers=bearer(admin_token))
    with SessionLocal() as db:
        assert db.get(Kit, kit_id).status == KitStatus.analysed, \
            "results may exist; un-analysing a kit behind the user's back would be worse"
