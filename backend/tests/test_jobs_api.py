import pytest

from tests.conftest import bearer, register, user_id, panel_id


@pytest.fixture(autouse=True)
def no_enqueue(monkeypatch):
    """Don't hit Redis/Celery/ECS during API tests; record enqueued job ids instead."""
    calls = []
    monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: calls.append(job_id))
    return calls


def _make_kit(client, admin_token, assigned_ids, code="DIVJA240") -> int:
    return client.post(
        "/api/kits",
        json={
            "kit_code": code, "panel_id": panel_id("UA_primers"),
            "selected_tags": ["PP1", "PP2", "PP3", "PP4", "PP5", "PP6", "PP7", "PP8"],
            "assigned_user_ids": assigned_ids,
        },
        headers=bearer(admin_token),
    ).json()["id"]


def job_payload(kit_id):
    return {
        "kit_id": kit_id,
        "fastq_source": "upload",
        "fastq1_ref": "uploads/1/x/reads_1.fastq.gz",
        "fastq2_ref": "uploads/1/x/reads_2.fastq.gz",
        "expected_read_number": 10_000_000,
        "batches": [
            {"name": "HRM01", "sample_sheet_key": "uploads/1/x/HRM01.xlsx",
             "selected_tags": ["PP1", "PP2", "PP3", "PP4"]},
            {"name": "HRM02", "sample_names_text": "S1\nS2\nS3",
             "selected_tags": ["PP5", "PP6", "PP7", "PP8"]},
        ],
    }


def test_create_job_requires_kit_access(client, catalog, admin_token, user_token):
    """A user without access to the kit cannot submit a job for it."""
    kit_id = _make_kit(client, admin_token, assigned_ids=[])  # assigned to nobody
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 403 and "access" in r.text.lower()


def test_create_job_enqueues_when_granted(client, catalog, admin_token, user_token, no_enqueue):
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("user@x.com")])
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "queued" and len(job["batches"]) == 2
    assert len(no_enqueue) == 1


def test_rerun_job(client, catalog, admin_token, user_token, no_enqueue):
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]

    # can't rerun while it's still in flight (queued is non-terminal)
    assert client.post(f"/api/jobs/{pub}/rerun", headers=bearer(user_token)).status_code == 409

    # drive it to a terminal state, then rerun re-queues it and re-enqueues
    from app.db import SessionLocal
    from app.models import Job, JobStatus, ResultFile, ResultKind
    from sqlalchemy import select, func
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.public_id == pub))
        job.status = JobStatus.failed
        job.error_message = "boom"
        db.add(ResultFile(job_id=job.id, kind=ResultKind.genotypes, object_key="k", filename="f"))
        db.commit(); jid = job.id

    no_enqueue.clear()
    r = client.post(f"/api/jobs/{pub}/rerun", headers=bearer(user_token))
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert r.json()["error_message"] is None
    assert no_enqueue == [jid]                       # re-dispatched
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ResultFile).where(ResultFile.job_id == jid)) == 0

    # not your job → 403
    other = client.post("/api/auth/register",
                        json={"email": "q@x.com", "password": "qpass1234"}).json()["access_token"]
    assert client.post(f"/api/jobs/{pub}/rerun", headers=bearer(other)).status_code == 403


def test_analysed_kit_blocks_until_reanalyse(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    # admin marks the kit analysed → user can no longer submit
    client.patch(f"/api/kits/{kit_id}", json={"status": "analysed"}, headers=bearer(admin_token))
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 409 and "analysed" in r.text.lower()
    # admin re-approves → user can submit again
    ok = client.patch(f"/api/kits/{kit_id}", json={"status": "reanalyse"}, headers=bearer(admin_token))
    assert ok.status_code == 200 and ok.json()["status"] == "reanalyse"
    assert client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).status_code == 201


def test_reject_unknown_tag_columns(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    payload = job_payload(kit_id)
    payload["batches"][0]["selected_tags"] = ["PP1", "PP99"]
    assert client.post("/api/jobs", json=payload, headers=bearer(user_token)).status_code == 422


def _set_status(pub, status):
    """Force a job into a given status directly (bypassing the worker)."""
    from app.db import SessionLocal
    from app.models import Job, JobStatus
    with SessionLocal() as db:
        j = db.query(Job).filter_by(public_id=pub).first()
        j.status = JobStatus(status)
        db.commit()


def test_reject_overlapping_pp_columns(client, catalog, admin_token, user_token):
    """A PP column may belong to only one batch within a submission."""
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    payload = job_payload(kit_id)
    payload["batches"][1]["selected_tags"] = ["PP4", "PP5"]  # PP4 already in batch 0
    r = client.post("/api/jobs", json=payload, headers=bearer(user_token))
    assert r.status_code == 422 and "another batch" in r.text.lower()


def test_pp_cross_check_spans_all_batches(client, catalog, admin_token, user_token, no_enqueue):
    """Cross-check is N-way: a clash between non-adjacent batches (1 and 3) is caught."""
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    payload = job_payload(kit_id)
    payload["batches"] = [
        {"name": "b1", "sample_names_text": "S1", "selected_tags": ["PP1", "PP2"]},
        {"name": "b2", "sample_names_text": "S2", "selected_tags": ["PP3", "PP4"]},
        {"name": "b3", "sample_names_text": "S3", "selected_tags": ["PP5", "PP1"]},  # PP1 clashes b1
    ]
    r = client.post("/api/jobs", json=payload, headers=bearer(user_token))
    assert r.status_code == 422 and "PP1" in r.text
    # A clean 3-way partition is accepted.
    payload["batches"][2]["selected_tags"] = ["PP5", "PP6"]
    assert client.post("/api/jobs", json=payload, headers=bearer(user_token)).status_code == 201


def test_running_kit_blocks_resubmission(client, catalog, admin_token, user_token, no_enqueue):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    r1 = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r1.status_code == 201
    # second submit while the first is still queued/in-flight -> 409
    r2 = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r2.status_code == 409 and "already running" in r2.text.lower()
    # once the first job reaches a terminal state, submission is allowed again
    _set_status(r1.json()["public_id"], "failed")
    assert client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).status_code == 201


def test_request_reanalysis_succeeded_only(client, catalog, admin_token, user_token, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.api.jobs.notify.send_reanalysis_requested", lambda *a, **k: sent.append(a)
    )
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    # not succeeded yet -> 409, no email
    r = client.post(f"/api/jobs/{pub}/request-reanalysis", json={"reason": "rerun"}, headers=bearer(user_token))
    assert r.status_code == 409 and not sent
    # succeeded -> 204 and the admin is emailed
    _set_status(pub, "succeeded")
    r = client.post(f"/api/jobs/{pub}/request-reanalysis", json={"reason": "rerun"}, headers=bearer(user_token))
    assert r.status_code == 204 and len(sent) == 1


def test_request_reanalysis_requires_ownership(client, catalog, admin_token, user_token, monkeypatch):
    monkeypatch.setattr("app.api.jobs.notify.send_reanalysis_requested", lambda *a, **k: None)
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    _set_status(pub, "succeeded")
    other = register(client, "other@x.com")
    assert client.post(
        f"/api/jobs/{pub}/request-reanalysis", json={"reason": "x"}, headers=bearer(other)
    ).status_code == 403


def test_batch_requires_samples(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    payload = job_payload(kit_id)
    payload["batches"][0] = {"name": "bad", "selected_tags": ["PP1"]}
    assert client.post("/api/jobs", json=payload, headers=bearer(user_token)).status_code == 422


def test_ownership_isolation(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    other = register(client, "other@x.com")
    assert client.get(f"/api/jobs/{pub}", headers=bearer(other)).status_code == 403
    assert client.get(f"/api/jobs/{pub}", headers=bearer(user_token)).status_code == 200
    assert len(client.get("/api/jobs", headers=bearer(user_token)).json()) == 1
    assert client.get("/api/jobs", headers=bearer(other)).json() == []


def _pause_job(pub, observed=500):
    """Simulate the worker pausing a job for low reads."""
    from app.db import SessionLocal
    from app.models import Job, JobStatus
    with SessionLocal() as db:
        j = db.query(Job).filter_by(public_id=pub).first()
        j.status = JobStatus.awaiting_confirmation
        j.observed_read_count = observed
        db.commit()


def test_confirm_runs_low_read_job(client, catalog, admin_token, user_token, no_enqueue):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    _pause_job(pub)
    no_enqueue.clear()
    r = client.post(f"/api/jobs/{pub}/confirm", json={"proceed": True}, headers=bearer(user_token))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued" and body["reads_confirmed"] is True
    assert len(no_enqueue) == 1  # re-dispatched


def test_confirm_cancel_low_read_job(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    _pause_job(pub)
    r = client.post(f"/api/jobs/{pub}/confirm", json={"proceed": False}, headers=bearer(user_token))
    assert r.status_code == 200 and r.json()["status"] == "failed"


def test_confirm_only_when_awaiting(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    # still queued -> confirming is a 409
    assert client.post(f"/api/jobs/{pub}/confirm", json={"proceed": True}, headers=bearer(user_token)).status_code == 409


def test_init_upload_small_uses_put(client, user_token):
    r = client.post(
        "/api/jobs/uploads",
        json={"filename": "HRM01.xlsx", "size": 1024, "purpose": "sample"},
        headers=bearer(user_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "put" and body["put_url"] and body["key"].endswith("HRM01.xlsx")
