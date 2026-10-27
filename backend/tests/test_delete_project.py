"""Delete-project: cascades all data, keeps (detaches) jobs, owner-only."""
import uuid

from sqlalchemy import select, func

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Job, JobStatus, FastqSource,
    Sample, ConsensusGenotype, ReferenceAllele, MatchSubgroup,
)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_delete_project_cascades_and_keeps_jobs(client, admin_token):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Doomed", owner_user_id=u.id)
        db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="P"); db.add(pop); db.flush()
        study = Study(project_id=proj.id, population_id=pop.id, name="S"); db.add(study); db.flush()
        ra = ReferenceAllele(project_id=proj.id, marker="M1", sequence="M1a", allele_name="a")
        db.add(ra); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code="S-1", project_id=proj.id,
                   population_id=pop.id, name="w"); db.add(s); db.flush()
        db.add(ConsensusGenotype(sample_id=s.id, marker="M1", allele1="a", allele1_id=ra.id))
        sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=pop.id, label="A",
                           reference_sample_id=s.id, n_samples=1); db.add(sg); db.flush()
        s.subgroup_id = sg.id
        job = Job(public_id=uuid.uuid4().hex, user_id=u.id, kit_id=1, status=JobStatus.succeeded,
                  fastq_source=FastqSource.upload, project_id=proj.id,
                  default_population_id=pop.id, default_study_id=study.id)
        db.add(job); db.commit()
        pid, jid = proj.id, job.id

    assert client.delete(f"/api/projects/{pid}", headers=_hdr(admin_token)).status_code == 204

    with SessionLocal() as db:
        assert db.get(Project, pid) is None
        assert db.scalar(select(func.count()).select_from(Population).where(Population.project_id == pid)) == 0
        assert db.scalar(select(func.count()).select_from(Sample).where(Sample.project_id == pid)) == 0
        assert db.scalar(select(func.count()).select_from(ReferenceAllele).where(ReferenceAllele.project_id == pid)) == 0
        assert db.query(ConsensusGenotype).count() == 0
        # the job survives, detached from the deleted project
        job = db.get(Job, jid)
        assert job is not None and job.project_id is None and job.default_population_id is None


def test_delete_project_owner_only(client, admin_token, user_token):
    pid = client.post("/api/projects", json={"name": "Mine"}, headers=_hdr(admin_token)).json()["id"]
    # share as editor — still not allowed to delete (owner only)
    client.post(f"/api/projects/{pid}/share", json={"email": "user@x.com", "role": "editor"},
                headers=_hdr(admin_token))
    assert client.delete(f"/api/projects/{pid}", headers=_hdr(user_token)).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=_hdr(admin_token)).status_code == 204
