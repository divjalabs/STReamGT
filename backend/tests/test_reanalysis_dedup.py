"""Reanalysing a kit updates samples in place (no duplicates) + one-off dedup of existing dupes."""
import uuid

from sqlalchemy import select, func

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Job, JobStatus, FastqSource,
    Sample, Sex, ConsensusGenotype, ReplicateObservation,
)
from app.services import consensus_parsers as P
from app.services.ingestion import ingest_parsed
from app.services.sample_dedup import dedup_duplicate_samples
from tests.test_projects_ingestion import CONSENSUS, REFERENCE, GENOTYPES, POSITIONS


def _seed(db):
    u = db.scalar(select(User).where(User.email == "admin@x.com"))
    proj = Project(public_id=uuid.uuid4().hex, name="P", owner_user_id=u.id); db.add(proj); db.flush()
    pop = Population(project_id=proj.id, name="Pop"); db.add(pop); db.commit()
    return u, proj, pop


def _job(db, u, proj, pop, kit_id=1):
    job = Job(public_id=uuid.uuid4().hex, user_id=u.id, kit_id=kit_id, status=JobStatus.succeeded,
              fastq_source=FastqSource.upload, project_id=proj.id, default_population_id=pop.id)
    db.add(job); db.commit(); return job


def _ingest(db, job):
    ingest_parsed(db, job,
                  consensus=P.parse_consensus(CONSENSUS), ref_alleles=P.parse_reference_alleles(REFERENCE),
                  genotypes=P.parse_genotypes(GENOTYPES), positions=P.parse_positions(POSITIONS))
    db.commit()


def test_reanalysis_updates_in_place_no_duplicates(client, admin_token):
    with SessionLocal() as db:
        u, proj, pop = _seed(db)
        _ingest(db, _job(db, u, proj, pop))            # first analysis
        n1 = db.scalar(select(func.count()).select_from(Sample).where(Sample.project_id == proj.id))
        job2 = _job(db, u, proj, pop)                  # reanalysis: new job, same kit/project/names
        _ingest(db, job2)
        n2 = db.scalar(select(func.count()).select_from(Sample).where(Sample.project_id == proj.id))
        assert n2 == n1 and n1 > 0                      # no duplication
        # every specimen now points at the latest run
        for s in db.scalars(select(Sample).where(Sample.project_id == proj.id)):
            assert s.job_id == job2.id


def test_dedup_removes_existing_duplicates(client, admin_token):
    with SessionLocal() as db:
        u, proj, pop = _seed(db)
        job1, job2 = _job(db, u, proj, pop), _job(db, u, proj, pop)
        old = Sample(public_id=uuid.uuid4().hex, system_code="S-old", project_id=proj.id, kit_id=1,
                     name="X", job_id=job1.id, population_id=pop.id, sex=Sex.unknown)
        new = Sample(public_id=uuid.uuid4().hex, system_code="S-new", project_id=proj.id, kit_id=1,
                     name="X", job_id=job2.id, population_id=pop.id, sex=Sex.unknown)
        db.add_all([old, new]); db.flush()
        db.add(ConsensusGenotype(sample_id=new.id, marker="M1", allele1="12"))
        db.add(ReplicateObservation(sample_id=new.id, marker="M1"))
        db.add(ReplicateObservation(sample_id=old.id, marker="M1"))
        db.commit()
        keep_id = new.id

        summary = dedup_duplicate_samples(db); db.commit()
        assert summary["deleted"] == 1 and summary["groups"] == 1
        rows = db.scalars(select(Sample).where(Sample.project_id == proj.id, Sample.name == "X")).all()
        assert len(rows) == 1 and rows[0].id == keep_id            # kept the most-recent job's copy
        assert db.scalar(select(func.count()).select_from(ConsensusGenotype)
                         .where(ConsensusGenotype.sample_id == keep_id)) == 1   # survivor's data intact
