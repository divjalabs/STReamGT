"""Delete populations and studies (Project detail page).

- delete study: samples stay, fall back to the study's parent population.
- delete population: transfer its samples+studies to another population, or delete them; 409 when
  non-empty and no directive given.
"""
import uuid

from sqlalchemy import select, func

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Sample, ConsensusGenotype, ReferenceAllele, MatchSubgroup,
)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed(with_matching=False):
    """A project with Pop1 (Study S1 + one sample) and an empty Pop2."""
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="P", owner_user_id=u.id)
        db.add(proj); db.flush()
        p1 = Population(project_id=proj.id, name="Pop1")
        p2 = Population(project_id=proj.id, name="Pop2")
        db.add_all([p1, p2]); db.flush()
        study = Study(project_id=proj.id, population_id=p1.id, name="S1"); db.add(study); db.flush()
        ra = ReferenceAllele(project_id=proj.id, marker="M1", sequence="M1a", allele_name="a")
        db.add(ra); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{uuid.uuid4().hex[:6]}",
                   project_id=proj.id, population_id=p1.id, study_id=study.id, name="w1")
        db.add(s); db.flush()
        db.add(ConsensusGenotype(sample_id=s.id, marker="M1", allele1="a", allele1_id=ra.id))
        if with_matching:
            sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=p1.id, label="A",
                               reference_sample_id=s.id, n_samples=1)
            db.add(sg); db.flush()
            s.subgroup_id = sg.id
        db.commit()
        return proj.id, p1.id, p2.id, study.id, s.id


def test_delete_study_keeps_samples_in_population(client, admin_token):
    pid, p1, p2, study_id, sid = _seed()
    assert client.delete(f"/api/studies/{study_id}", headers=_hdr(admin_token)).status_code == 204
    with SessionLocal() as db:
        assert db.get(Study, study_id) is None
        s = db.get(Sample, sid)
        assert s is not None and s.study_id is None and s.population_id == p1


def test_delete_empty_population(client, admin_token):
    pid, p1, p2, study_id, sid = _seed()
    # Pop2 is empty → deletes straight away
    assert client.delete(f"/api/projects/{pid}/populations/{p2}", headers=_hdr(admin_token)).status_code == 204
    with SessionLocal() as db:
        assert db.get(Population, p2) is None
        assert db.get(Population, p1) is not None


def test_delete_nonempty_population_requires_directive(client, admin_token):
    pid, p1, p2, study_id, sid = _seed()
    r = client.delete(f"/api/projects/{pid}/populations/{p1}", headers=_hdr(admin_token))
    assert r.status_code == 409 and "sample" in r.text.lower()
    # nothing deleted
    with SessionLocal() as db:
        assert db.get(Population, p1) is not None


def test_delete_population_transfers_samples_and_studies(client, admin_token):
    pid, p1, p2, study_id, sid = _seed(with_matching=True)
    r = client.delete(f"/api/projects/{pid}/populations/{p1}?reassign_to={p2}", headers=_hdr(admin_token))
    assert r.status_code == 204, r.text
    with SessionLocal() as db:
        assert db.get(Population, p1) is None
        s = db.get(Sample, sid)
        assert s.population_id == p2 and s.subgroup_id is None      # moved, animal assignment cleared
        assert db.get(Study, study_id).population_id == p2           # study moved with it
        assert db.scalar(select(func.count()).select_from(MatchSubgroup)
                         .where(MatchSubgroup.population_id == p1)) == 0


def test_delete_population_transfer_rejects_bad_target(client, admin_token):
    pid, p1, p2, study_id, sid = _seed()
    # reassign to itself → 422
    assert client.delete(f"/api/projects/{pid}/populations/{p1}?reassign_to={p1}",
                         headers=_hdr(admin_token)).status_code == 422


def test_delete_population_force_deletes_samples_and_studies(client, admin_token):
    pid, p1, p2, study_id, sid = _seed(with_matching=True)
    r = client.delete(f"/api/projects/{pid}/populations/{p1}?delete_samples=true", headers=_hdr(admin_token))
    assert r.status_code == 204, r.text
    with SessionLocal() as db:
        assert db.get(Population, p1) is None
        assert db.get(Study, study_id) is None
        assert db.get(Sample, sid) is None
        assert db.query(ConsensusGenotype).count() == 0
        assert db.get(Population, p2) is not None                    # the other population survives


def test_population_list_reports_sample_count(client, admin_token):
    pid, p1, p2, study_id, sid = _seed()
    rows = {p["id"]: p["sample_count"] for p in
            client.get(f"/api/projects/{pid}/populations", headers=_hdr(admin_token)).json()}
    assert rows[p1] == 1 and rows[p2] == 0
