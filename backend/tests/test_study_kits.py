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


def test_attach_detach_moves_samples(client, catalog, admin_token):
    import uuid
    from app.models import Sample, MatchSubgroup, Sex
    pid = client.post("/api/projects", json={"name": "P"}, headers=bearer(admin_token)).json()["id"]
    p1 = client.post(f"/api/projects/{pid}/populations", json={"name": "P1"},
                     headers=bearer(admin_token)).json()
    p2 = client.post(f"/api/projects/{pid}/populations", json={"name": "P2"},
                     headers=bearer(admin_token)).json()
    sA = client.post(f"/api/projects/{pid}/studies", json={"name": "A", "population_id": p1["id"]},
                     headers=bearer(admin_token)).json()
    sB = client.post(f"/api/projects/{pid}/studies", json={"name": "B", "population_id": p2["id"]},
                     headers=bearer(admin_token)).json()
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("admin@x.com")])

    # two of the kit's samples, sitting in study A / pop P1, grouped into an animal
    with SessionLocal() as db:
        s1 = Sample(public_id=uuid.uuid4().hex, system_code="S-1", project_id=pid,
                    population_id=p1["id"], study_id=sA["id"], kit_id=kit_id, name="X1", sex=Sex.unknown)
        s2 = Sample(public_id=uuid.uuid4().hex, system_code="S-2", project_id=pid,
                    population_id=p1["id"], study_id=sA["id"], kit_id=kit_id, name="X2", sex=Sex.unknown)
        db.add_all([s1, s2]); db.flush()
        sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=p1["id"], label="A1",
                           reference_sample_id=s1.id, n_samples=2)
        db.add(sg); db.flush()
        s1.subgroup_id = s2.subgroup_id = sg.id
        db.commit()
        ids = [s1.id, s2.id]

    client.post(f"/api/studies/{sA['id']}/kits/{kit_id}", headers=bearer(admin_token))

    # move the kit to study B -> samples follow to B / P2, animal grouping cleared, kit off study A
    r = client.post(f"/api/studies/{sB['id']}/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert client.get(f"/api/studies/{sA['id']}", headers=bearer(admin_token)).json()["kits"] == []
    assert [k["id"] for k in r.json()["kits"]] == [kit_id]
    with SessionLocal() as db:
        for sid in ids:
            s = db.get(Sample, sid)
            assert s.study_id == sB["id"] and s.population_id == p2["id"] and s.subgroup_id is None

    # detach -> samples unassigned from study + population
    client.delete(f"/api/studies/{sB['id']}/kits/{kit_id}", headers=bearer(admin_token))
    with SessionLocal() as db:
        for sid in ids:
            s = db.get(Sample, sid)
            assert s.study_id is None and s.population_id is None


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
