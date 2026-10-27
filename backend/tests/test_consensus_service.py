"""M2: recompute from replicates (sequence-level), edit + lock, and lock-preservation on rerun."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Job, JobStatus, FastqSource,
    Sample, ConsensusGenotype, ConsensusEditLog,
)
from app.services import consensus_parsers as P
from app.services.ingestion import ingest_parsed

A, B, C = "A" * 12, "A" * 14, "A" * 16   # names 12, 14, 16


def _tsv(header, rows):
    return "\n".join(["\t".join(header)] + ["\t".join(map(str, r)) for r in rows]) + "\n"


# Self-consistent fixture: replicates genuinely support a 12/14 heterozygote (with a dropout
# well and a false-allele well), so recompute reproduces the ingested consensus.
CONSENSUS = _tsv(
    ["Sample", "Mrkr", "Al1", "Al2", "Al3", "Al4", "NcnfA1", "NCnfA2", "ConfirmedAlleles",
     "UnconfirmedAlleles", "NAmp", "NAmpOK", "Success", "ADO", "ADORate", "QualityIndex",
     "FalseAlleles", "ReadsPerAmp", "SD_ReadsPerAmp"],
    [["S1", "M1", "12", "14", "", "", "", "", "", "16", 4, 4, 100.0, 2, 0.5, 0.5, 1, 631, 441.7838]],
)
REFERENCE = _tsv(
    ["Marker", "Sequence", "Length", "Variant", "AlleleName", "N"],
    [["M1", A, 12, 1, "12", 5], ["M1", B, 14, 1, "14", 2], ["M1", C, 16, 1, "16", 1]],
)
GENOTYPES = _tsv(
    ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position",
     "called", "flag", "stutter", "Sequence", "TagCombo"],
    [["S1", "PP1", 500, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP1"],
     ["S1", "PP1", 480, "M1", "kit", 14, 1, "TRUE", "", "FALSE", B, "PP1"],
     ["S1", "PP2", 510, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP2"],
     ["S1", "PP2", 470, "M1", "kit", 14, 1, "TRUE", "", "FALSE", B, "PP2"],
     ["S1", "PP3", 505, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP3"],
     ["S1", "PP4", 60, "M1", "kit", 16, 1, "TRUE", "", "FALSE", C, "PP4"]],
)
POSITIONS = _tsv(
    ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position", "TagCombo"],
    [["S1", p, "", "M1", "kit", "", 1, p] for p in ("PP1", "PP2", "PP3", "PP4")],
)


def _seed_and_ingest():
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Wolves", owner_user_id=u.id)
        db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Dinaric"); db.add(pop); db.flush()
        study = Study(project_id=proj.id, population_id=pop.id, name="2025"); db.add(study); db.flush()
        job = Job(public_id=uuid.uuid4().hex, user_id=u.id, kit_id=1, status=JobStatus.succeeded,
                  fastq_source=FastqSource.upload, project_id=proj.id,
                  default_population_id=pop.id, default_study_id=study.id)
        db.add(job); db.commit()
        ingest_parsed(db, job,
                      consensus=P.parse_consensus(CONSENSUS),
                      ref_alleles=P.parse_reference_alleles(REFERENCE),
                      genotypes=P.parse_genotypes(GENOTYPES),
                      positions=P.parse_positions(POSITIONS))
        db.commit()
        sid = db.scalar(select(Sample.id).where(Sample.name == "S1"))
        cid = db.scalar(select(ConsensusGenotype.id).where(ConsensusGenotype.sample_id == sid))
        return sid, cid


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_recompute_edit_lock(client, admin_token):
    sid, cid = _seed_and_ingest()

    # recompute from replicates reproduces the 12/14 heterozygote (sequence-level)
    r = client.post(f"/api/samples/{sid}/rerun-consensus", headers=_hdr(admin_token))
    assert r.status_code == 200, r.text
    row = r.json()[0]
    assert (row["allele1"], row["allele2"]) == ("12", "14")
    assert row["quality_index"] == 0.5 and row["ado"] == 2
    assert row["source"] == "recomputed"

    # edit a call -> is_edited + audit-logged
    r = client.patch(f"/api/consensus/{cid}", json={"allele1": "99"}, headers=_hdr(admin_token))
    assert r.status_code == 200 and r.json()["allele1"] == "99" and r.json()["is_edited"] is True
    with SessionLocal() as db:
        assert db.scalar(select(ConsensusEditLog).where(ConsensusEditLog.consensus_id == cid)) is not None

    # lock -> the edit survives a rerun
    assert client.post(f"/api/consensus/{cid}/lock", headers=_hdr(admin_token)).json()["is_locked"] is True
    client.post(f"/api/samples/{sid}/rerun-consensus", headers=_hdr(admin_token))
    with SessionLocal() as db:
        assert db.get(ConsensusGenotype, cid).allele1 == "99"     # locked -> untouched

    # editing a locked genotype is refused
    assert client.patch(f"/api/consensus/{cid}", json={"allele1": "7"},
                        headers=_hdr(admin_token)).status_code == 409

    # unlock -> rerun recomputes back to 12
    client.post(f"/api/consensus/{cid}/unlock", headers=_hdr(admin_token))
    client.post(f"/api/samples/{sid}/rerun-consensus", headers=_hdr(admin_token))
    with SessionLocal() as db:
        assert db.get(ConsensusGenotype, cid).allele1 == "12"


def test_replicates_endpoint(client, admin_token):
    sid, _cid = _seed_and_ingest()
    r = client.get(f"/api/samples/{sid}/replicates", headers=_hdr(admin_token))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 6                       # 6 called observations
    assert {row["allele_name"] for row in rows} == {"12", "14", "16"}
    assert all(row["sequence"] for row in rows)  # sequence present (allele identity)
