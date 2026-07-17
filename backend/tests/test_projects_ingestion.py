"""M1: parsers, job-output ingestion (idempotency + lock), and the project/sample API."""
import uuid

from app.db import SessionLocal
from app.models import (
    User, UserRole, Project, Population, Study, Job, JobStatus, FastqSource,
    Sample, ConsensusGenotype, ReferenceAllele, ReplicateObservation, ReplicateAmplification,
)
from sqlalchemy import select

from app.services import consensus_parsers as P
from app.services.ingestion import ingest_parsed


def _tsv(header, rows):
    return "\n".join(["\t".join(header)] + ["\t".join(map(str, r)) for r in rows]) + "\n"


A, B = "A" * 12, "A" * 14  # AlleleNames "12", "14"

CONSENSUS = _tsv(
    ["Sample", "Mrkr", "Al1", "Al2", "Al3", "Al4", "NcnfA1", "NCnfA2", "ConfirmedAlleles",
     "UnconfirmedAlleles", "NAmp", "NAmpOK", "Success", "ADO", "ADORate", "QualityIndex",
     "FalseAlleles", "ReadsPerAmp", "SD_ReadsPerAmp"],
    [["S1", "M1", "12", "14", "", "", "", "", "", "", 4, 3, 75.0, 1, 0.333, 0.5, 1, 631, 441.78],
     ["S2", "M1", "12", "", "", "", "", "", "", "", 3, 3, 100.0, 0, 0.0, 1.0, 0, 500, 0.0]],
)
REFERENCE = _tsv(
    ["Marker", "Sequence", "Length", "Variant", "AlleleName", "N"],
    [["M1", A, 12, 1, "12", 5], ["M1", B, 14, 1, "14", 2]],
)
GENOTYPES = _tsv(
    ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position",
     "called", "flag", "stutter", "Sequence", "TagCombo"],
    [["S1", "PP1", 500, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP1"],
     ["S1", "PP1", 480, "M1", "kit", 14, 1, "TRUE", "", "FALSE", B, "PP1"],
     ["S1", "PP2", 100, "M1", "kit", 12, 1, "FALSE", "L", "FALSE", A, "PP2"],  # not called -> filtered
     ["S2", "PP1", 600, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP1"]],
)
POSITIONS = _tsv(
    ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position", "TagCombo"],
    [["S1", "PP1", "", "M1", "kit", "", 1, "PP1"],
     ["S1", "PP2", "", "M1", "kit", "", 1, "PP2"],
     ["S2", "PP1", "", "M1", "kit", "", 1, "PP1"]],
)


def test_parsers_basic_and_empty():
    cons = P.parse_consensus(CONSENSUS)
    assert len(cons) == 2
    s1 = next(c for c in cons if c.sample_name == "S1")
    assert (s1.allele1, s1.allele2, s1.quality_index, s1.ado, s1.false_alleles, s1.reads_per_amp) \
        == ("12", "14", 0.5, 1, 1, 631)
    assert len(P.parse_reference_alleles(REFERENCE)) == 2
    assert len(P.parse_genotypes(GENOTYPES)) == 3           # the called==FALSE row is dropped
    assert len(P.parse_genotypes(GENOTYPES, called_only=False)) == 4
    assert len(P.parse_positions(POSITIONS)) == 3
    # header-only / empty -> []
    assert P.parse_consensus("") == []
    assert P.parse_consensus("Sample\tMrkr\n") == []


def _seed_project_and_job(db):
    u = db.scalar(select(User).where(User.email == "admin@x.com"))
    proj = Project(public_id=uuid.uuid4().hex, name="Wolves", owner_user_id=u.id)
    db.add(proj); db.flush()
    pop = Population(project_id=proj.id, name="Dinaric"); db.add(pop); db.flush()
    study = Study(project_id=proj.id, population_id=pop.id, name="2025"); db.add(study); db.flush()
    job = Job(public_id=uuid.uuid4().hex, user_id=u.id, kit_id=1, status=JobStatus.succeeded,
              fastq_source=FastqSource.upload, project_id=proj.id,
              default_population_id=pop.id, default_study_id=study.id)
    db.add(job); db.commit()
    return proj.id, pop.id, job.id


def _ingest(db, job):
    return ingest_parsed(
        db, job,
        consensus=P.parse_consensus(CONSENSUS), ref_alleles=P.parse_reference_alleles(REFERENCE),
        genotypes=P.parse_genotypes(GENOTYPES), positions=P.parse_positions(POSITIONS),
    )


def test_ingestion_idempotent_and_lock(admin_token):
    with SessionLocal() as db:
        _proj_id, _pop_id, job_id = _seed_project_and_job(db)
        job = db.get(Job, job_id)
        s = _ingest(db, job); db.commit()
        assert s == {"samples": 2, "consensus": 2, "reference_alleles": 2,
                     "replicate_observations": 3, "replicate_amplifications": 3}
        assert db.query(Sample).count() == 2
        assert db.query(ReplicateObservation).count() == 3
        assert db.query(ReplicateAmplification).count() == 3
        # allele_name resolved from reference on a replicate observation
        ro = db.query(ReplicateObservation).filter(ReplicateObservation.sequence == A).first()
        assert ro.allele_name == "12"

        # consensus alleles are linked to their SEQUENCE-backed identity (reference_alleles), not
        # just the name string: allele1_id/allele2_id resolve to the right sequences.
        cg1 = db.query(ConsensusGenotype).join(Sample).filter(Sample.name == "S1").first()
        assert cg1.allele1_id is not None and cg1.allele2_id is not None
        assert db.get(ReferenceAllele, cg1.allele1_id).sequence == A  # name "12" -> len-12 seq
        assert db.get(ReferenceAllele, cg1.allele2_id).sequence == B  # name "14" -> len-14 seq

        # idempotent re-ingest: no duplication
        _ingest(db, job); db.commit()
        assert db.query(Sample).count() == 2
        assert db.query(ReplicateObservation).count() == 3
        assert db.query(ConsensusGenotype).count() == 2

        # lock preservation: a locked/edited consensus row survives re-ingest untouched
        cg = db.query(ConsensusGenotype).join(Sample).filter(Sample.name == "S1").first()
        cg.is_locked = True; cg.allele1 = "LOCKED"; db.commit()
        _ingest(db, job); db.commit()
        db.refresh(cg)
        assert cg.allele1 == "LOCKED"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_project_api_and_access(client, admin_token, user_token):
    # admin creates a project + population + study
    r = client.post("/api/projects", json={"name": "P1"}, headers=_hdr(admin_token))
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/populations", json={"name": "Pop"}, headers=_hdr(admin_token))
    pop_id = r.json()["id"]
    assert client.post(f"/api/projects/{pid}/studies", json={"name": "S", "population_id": pop_id},
                       headers=_hdr(admin_token)).status_code == 201
    # empty sample list for a fresh population
    r = client.get(f"/api/populations/{pop_id}/samples", headers=_hdr(admin_token))
    assert r.status_code == 200 and r.json() == []

    # the regular user has no access until shared
    assert client.get(f"/api/projects/{pid}", headers=_hdr(user_token)).status_code == 404
    assert client.post(f"/api/projects/{pid}/share", json={"email": "user@x.com", "role": "viewer"},
                       headers=_hdr(admin_token)).status_code == 204
    assert client.get(f"/api/projects/{pid}", headers=_hdr(user_token)).status_code == 200
    # viewer cannot create (needs editor)
    assert client.post(f"/api/projects/{pid}/populations", json={"name": "X"},
                       headers=_hdr(user_token)).status_code == 403
