"""Project allele-name curation: frequency auto-naming, fixed reservation, propagation, round-trip."""
import csv
import io
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Job, JobStatus, FastqSource,
    Sample, ConsensusGenotype, ReferenceAllele,
)
from app.services import consensus_parsers as P
from app.services.ingestion import ingest_parsed
from app.services.allele_naming import renormalize_allele_names

# Two length-12 sequences (A, D) + one length-14 (B). D accumulates MORE project reads than A,
# so re-normalizing must swap their names: D -> "12" (bare), A -> "12_2".
A, D, B = "A" * 12, "G" * 12, "A" * 14


def _tsv(header, rows):
    return "\n".join(["\t".join(header)] + ["\t".join(map(str, r)) for r in rows]) + "\n"


REFERENCE = _tsv(
    ["Marker", "Sequence", "Length", "Variant", "AlleleName", "N"],
    [["M1", A, 12, 1, "12", 330], ["M1", D, 12, 2, "12_2", 1020], ["M1", B, 14, 1, "14", 285]],
)
# S1 = het A(12)/B(14); S2 = homozygous D(12) with higher reads.
CONSENSUS = _tsv(
    ["Sample", "Mrkr", "Al1", "Al2", "Al3", "Al4", "NcnfA1", "NCnfA2", "ConfirmedAlleles",
     "UnconfirmedAlleles", "NAmp", "NAmpOK", "Success", "ADO", "ADORate", "QualityIndex",
     "FalseAlleles", "ReadsPerAmp", "SD_ReadsPerAmp"],
    [["S1", "M1", "12", "14", "", "", "", "", "12;14", "", 3, 3, 100.0, 0, 0.0, 1.0, 0, 100, 0.0],
     ["S2", "M1", "12_2", "", "", "", "", "", "12_2", "", 2, 2, 100.0, 0, 0.0, 1.0, 0, 510, 0.0]],
)
GENOTYPES = _tsv(
    ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position",
     "called", "flag", "stutter", "Sequence", "TagCombo"],
    [["S1", "PP1", 100, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP1"],
     ["S1", "PP2", 120, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP2"],
     ["S1", "PP3", 110, "M1", "kit", 12, 1, "TRUE", "", "FALSE", A, "PP3"],
     ["S1", "PP1", 90, "M1", "kit", 14, 1, "TRUE", "", "FALSE", B, "PP1"],
     ["S1", "PP2", 95, "M1", "kit", 14, 1, "TRUE", "", "FALSE", B, "PP2"],
     ["S1", "PP3", 100, "M1", "kit", 14, 1, "TRUE", "", "FALSE", B, "PP3"],
     ["S2", "PP5", 500, "M1", "kit", 12, 2, "TRUE", "", "FALSE", D, "PP5"],
     ["S2", "PP6", 520, "M1", "kit", 12, 2, "TRUE", "", "FALSE", D, "PP6"]],
)
POSITIONS = _tsv(
    ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position", "TagCombo"],
    [["S1", "PP1", "", "M1", "kit", "", 1, "PP1"], ["S1", "PP2", "", "M1", "kit", "", 1, "PP2"],
     ["S1", "PP3", "", "M1", "kit", "", 1, "PP3"],
     ["S2", "PP5", "", "M1", "kit", "", 2, "PP5"], ["S2", "PP6", "", "M1", "kit", "", 2, "PP6"]],
)


def _seed():
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
        return proj.id


def _names_by_seq(db, pid):
    return {a.sequence: a.allele_name
            for a in db.scalars(select(ReferenceAllele).where(ReferenceAllele.project_id == pid))}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_renormalize_reranks_by_project_reads(client, admin_token):
    pid = _seed()
    with SessionLocal() as db:
        renormalize_allele_names(db, pid)
        db.commit()
    with SessionLocal() as db:
        names = _names_by_seq(db, pid)
        assert names[D] == "12"      # D has more project reads -> bare length
        assert names[A] == "12_2"    # A demoted
        assert names[B] == "14"
        # propagation to consensus display names (calls unchanged, identity by sequence)
        s1 = db.scalar(select(ConsensusGenotype).join(Sample).where(Sample.name == "S1"))
        s2 = db.scalar(select(ConsensusGenotype).join(Sample).where(Sample.name == "S2"))
        assert (s1.allele1, s1.allele2) == ("12_2", "14")   # A renamed 12 -> 12_2
        assert s1.confirmed_alleles == "12_2;14"            # token-remapped
        assert s2.allele1 == "12"                           # D renamed 12_2 -> 12


def test_fixed_name_reserved_frees_bare(client, admin_token):
    pid = _seed()
    with SessionLocal() as db:
        a = db.scalar(select(ReferenceAllele).where(
            ReferenceAllele.project_id == pid, ReferenceAllele.sequence == A))
        a.is_fixed, a.allele_name = True, "REF_A"
        db.flush()
        renormalize_allele_names(db, pid)
        db.commit()
    with SessionLocal() as db:
        names = _names_by_seq(db, pid)
        assert names[A] == "REF_A"   # fixed, untouched
        assert names[D] == "12"      # only non-fixed len-12 -> bare (REF_A doesn't collide)


def test_fixed_bare_pushes_nonfixed(client, admin_token):
    pid = _seed()
    with SessionLocal() as db:
        renormalize_allele_names(db, pid, fixed_names={
            db.scalar(select(ReferenceAllele.id).where(
                ReferenceAllele.project_id == pid, ReferenceAllele.sequence == A)): "12"})
        db.commit()
    with SessionLocal() as db:
        names = _names_by_seq(db, pid)
        assert names[A] == "12"       # fixed bare
        assert names[D] == "12_2"     # pushed off the bare slot


def test_export_import_roundtrip(client, admin_token):
    pid = _seed()
    # download
    r = client.get(f"/api/projects/{pid}/export/allele_names", headers=_hdr(admin_token))
    assert r.status_code == 200 and "allele_name" in r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert {row["sequence"] for row in rows} == {A, D, B}

    # pin D as a canonical name; leave A explicitly non-fixed
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["marker", "sequence", "allele_name", "is_fixed"])
    w.writerow(["M1", D, "CANON", "TRUE"])
    w.writerow(["M1", A, "12", "FALSE"])
    up = client.post(f"/api/projects/{pid}/import/allele-names", headers=_hdr(admin_token),
                     files={"file": ("names.csv", io.BytesIO(out.getvalue().encode()), "text/csv")})
    assert up.status_code == 200, up.text
    assert up.json()["fixed"] == 1
    with SessionLocal() as db:
        names = _names_by_seq(db, pid)
        assert names[D] == "CANON"           # pinned
        assert names[A] in ("12", "12_2")    # auto (bare free since D is fixed off-length-name)


def test_import_bad_columns_422(client, admin_token):
    pid = _seed()
    bad = b"marker,allele_name\nM1,12\n"
    r = client.post(f"/api/projects/{pid}/import/allele-names", headers=_hdr(admin_token),
                    files={"file": ("bad.csv", io.BytesIO(bad), "text/csv")})
    assert r.status_code == 422 and "sequence" in r.text
