"""PATCH /samples/{id}: study<->population consistency guard."""
import uuid

from app.db import SessionLocal
from app.models import Sample, Sex
from tests.conftest import bearer


def _setup(client, token, name="P"):
    pid = client.post("/api/projects", json={"name": name}, headers=bearer(token)).json()["id"]
    p1 = client.post(f"/api/projects/{pid}/populations", json={"name": "P1"}, headers=bearer(token)).json()
    p2 = client.post(f"/api/projects/{pid}/populations", json={"name": "P2"}, headers=bearer(token)).json()
    a = client.post(f"/api/projects/{pid}/studies", json={"name": "A", "population_id": p1["id"]},
                    headers=bearer(token)).json()
    b = client.post(f"/api/projects/{pid}/studies", json={"name": "B", "population_id": p2["id"]},
                    headers=bearer(token)).json()
    return pid, p1["id"], p2["id"], a["id"], b["id"]


def _sample(pid, code="S-1", **kw):
    with SessionLocal() as db:
        s = Sample(public_id=uuid.uuid4().hex, system_code=code, project_id=pid,
                   name="X", sex=Sex.unknown, **kw)
        db.add(s); db.commit()
        return s.id


def test_assigning_study_pulls_in_its_population(client, admin_token):
    pid, p1, p2, a, b = _setup(client, admin_token)
    sid = _sample(pid)                                   # orphan: no pop, no study
    r = client.patch(f"/api/samples/{sid}", json={"study_id": b}, headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["study_id"] == b and r.json()["population_id"] == p2   # population followed


def test_conflicting_study_and_population_rejected(client, admin_token):
    pid, p1, p2, a, b = _setup(client, admin_token)
    sid = _sample(pid)
    r = client.patch(f"/api/samples/{sid}", json={"study_id": b, "population_id": p1},
                     headers=bearer(admin_token))
    assert r.status_code == 422 and "different population" in r.text


def test_population_change_conflicting_with_current_study_rejected(client, admin_token):
    pid, p1, p2, a, b = _setup(client, admin_token)
    sid = _sample(pid, population_id=p1, study_id=a)     # in study A / pop P1
    r = client.patch(f"/api/samples/{sid}", json={"population_id": p2}, headers=bearer(admin_token))
    assert r.status_code == 422 and "another population" in r.text


def test_clearing_study_still_allowed(client, admin_token):
    pid, p1, p2, a, b = _setup(client, admin_token)
    sid = _sample(pid, population_id=p1, study_id=a)
    r = client.patch(f"/api/samples/{sid}", json={"study_id": None}, headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["study_id"] is None


def test_bulk_assign_to_study(client, admin_token):
    pid, p1, p2, a, b = _setup(client, admin_token)
    ids = [_sample(pid, code=f"S-{i}") for i in range(3)]     # orphans
    r = client.post(f"/api/projects/{pid}/samples/assign-study",
                    json={"sample_ids": ids, "study_id": b}, headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["assigned"] == 3
    with SessionLocal() as db:
        for sid in ids:
            s = db.get(Sample, sid)
            assert s.study_id == b and s.population_id == p2 and s.subgroup_id is None


def test_bulk_assign_rejects_foreign_study(client, admin_token):
    pid, p1, p2, a, b = _setup(client, admin_token)
    other_pid, _op1, _op2, _oa, ob = _setup(client, admin_token, name="Other")   # study in another project
    sid = _sample(pid)
    r = client.post(f"/api/projects/{pid}/samples/assign-study",
                    json={"sample_ids": [sid], "study_id": ob}, headers=bearer(admin_token))
    assert r.status_code == 422 and "not in this project" in r.text
