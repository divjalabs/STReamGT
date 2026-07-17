"""Kit<->study attachment: attach/detach, StudyOut.kits, and job auto-targeting.

Attaching a kit to a study also makes a job on that kit default its ingestion target to the
study (project + population + study), which fills the gap left by the Submit page.
"""
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job
from tests.conftest import bearer, user_id
from tests.test_jobs_api import _make_kit, job_payload, no_enqueue  # noqa: F401


def _project(client, token):
    pid = client.post("/api/projects", json={"name": "Proj"}, headers=bearer(token)).json()["id"]
    pop = client.post(f"/api/projects/{pid}/populations", json={"name": "Pop"},
                      headers=bearer(token)).json()
    study = client.post(f"/api/projects/{pid}/studies",
                        json={"name": "Study A", "population_id": pop["id"]},
                        headers=bearer(token)).json()
    return pid, pop["id"], study["id"]


def test_population_create_ignores_code(client, admin_token):
    """`code` was removed — the API neither accepts nor returns it."""
    pid = client.post("/api/projects", json={"name": "P"}, headers=bearer(admin_token)).json()["id"]
    r = client.post(f"/api/projects/{pid}/populations", json={"name": "Pop", "code": "XYZ"},
                    headers=bearer(admin_token))
    assert r.status_code == 201, r.text
    assert "code" not in r.json()


def test_attach_and_detach_kit(client, catalog, admin_token):
    pid, _, sid = _project(client, admin_token)
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("admin@x.com")])

    r = client.post(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert [k["kit_code"] for k in r.json()["kits"]] == ["DIVJA240"]

    # idempotent — attaching again keeps a single link
    r = client.post(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(admin_token))
    assert len(r.json()["kits"]) == 1

    # GET study reflects the attachment
    assert len(client.get(f"/api/studies/{sid}", headers=bearer(admin_token)).json()["kits"]) == 1

    r = client.delete(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 200 and r.json()["kits"] == []


def test_attach_requires_kit_access(client, catalog, admin_token, user_token):
    """A user with project edit rights but no access to the kit cannot attach it."""
    pid, _, sid = _project(client, user_token)
    kit_id = _make_kit(client, admin_token, assigned_ids=[])  # user has no kit access
    r = client.post(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(user_token))
    assert r.status_code == 403


def test_job_auto_targets_single_attached_study(client, catalog, admin_token, no_enqueue):
    pid, pop_id, sid = _project(client, admin_token)
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("admin@x.com")])
    client.post(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(admin_token))

    # No project target in the payload → derived from the kit's single attached study.
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(admin_token))
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.public_id == r.json()["public_id"]))
        assert job.project_id == pid
        assert job.default_population_id == pop_id
        assert job.default_study_id == sid


def test_job_no_target_when_no_attachment(client, catalog, admin_token, no_enqueue):
    _make = _make_kit(client, admin_token, assigned_ids=[user_id("admin@x.com")])
    r = client.post("/api/jobs", json=job_payload(_make), headers=bearer(admin_token))
    assert r.status_code == 201
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.public_id == r.json()["public_id"]))
        assert job.project_id is None and job.default_study_id is None
