"""Import/export: JSON round-trip, CSV genotype import, and the CSV/GenePop exports."""
import io
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Sample, ConsensusGenotype, ReferenceAllele, MatchSubgroup,
)
from app.services import porting

MARKERS = ["M1", "M2", "M3"]


def _seed():
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Src", owner_user_id=u.id); db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Din"); db.add(pop); db.flush()
        db.add(Study(project_id=proj.id, population_id=pop.id, name="2025")); db.flush()
        ref = {}
        for m in MARKERS:
            for tag in ("a", "b"):
                r = ReferenceAllele(project_id=proj.id, marker=m, sequence=f"{m}{tag}", allele_name=tag)
                db.add(r); ref[(m, tag)] = r
        db.flush()

        def mk(name):
            s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{name}", project_id=proj.id,
                       population_id=pop.id, name=name, genotype_ok=True)
            db.add(s); db.flush()
            for m in MARKERS:
                hom = (m == "M2")
                db.add(ConsensusGenotype(
                    sample_id=s.id, marker=m, allele1="a", allele1_id=ref[(m, "a")].id,
                    allele2=None if hom else "b", allele2_id=None if hom else ref[(m, "b")].id,
                    quality_index=0.9))
            return s
        s1, s2 = mk("W1"), mk("W2")
        sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=pop.id, label="A1",
                           reference_sample_id=s1.id, n_samples=2)
        db.add(sg); db.flush()
        s1.subgroup_id = sg.id; s2.subgroup_id = sg.id
        db.commit()
        return proj.id, u.id


def test_json_round_trip(client, admin_token):
    src_id, owner = _seed()
    with SessionLocal() as db:
        data = porting.project_json(db, src_id)
    assert len(data["samples"]) == 2 and len(data["reference_alleles"]) == 6

    with SessionLocal() as db:
        new = porting.import_project_json(db, owner, data)
        db.commit()
        nid = new.id
    with SessionLocal() as db:
        samples = db.scalars(select(Sample).where(Sample.project_id == nid)).all()
        assert len(samples) == 2
        assert db.query(ConsensusGenotype).join(Sample).filter(Sample.project_id == nid).count() == 6
        assert db.query(ReferenceAllele).filter(ReferenceAllele.project_id == nid).count() == 6
        assert db.query(MatchSubgroup).filter(MatchSubgroup.population_id.in_(
            select(Population.id).where(Population.project_id == nid))).count() == 1
        # a consensus allele resolves to the same SEQUENCE identity (round-trip preserved)
        cg = db.scalar(select(ConsensusGenotype).join(Sample)
                       .where(Sample.project_id == nid, ConsensusGenotype.marker == "M1"))
        assert db.get(ReferenceAllele, cg.allele1_id).sequence == "M1a"


def test_genotypes_csv_export_import(client, admin_token):
    src_id, owner = _seed()
    with SessionLocal() as db:
        csv_text = porting.genotypes_csv(db, src_id)
    assert "M1_1" in csv_text and "M1_2" in csv_text and "W1" in csv_text

    # import into a fresh project
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        dest = Project(public_id=uuid.uuid4().hex, name="Dest", owner_user_id=u.id)
        db.add(dest); db.flush()
        summary = porting.import_genotypes_csv(db, dest.id, csv_text)
        db.commit()
        did = dest.id
    assert summary == {"samples": 2, "consensus": 6, "markers": 3}
    with SessionLocal() as db:
        cg = db.scalar(select(ConsensusGenotype).join(Sample)
                       .where(Sample.project_id == did, ConsensusGenotype.marker == "M1"))
        assert cg.allele1 == "a" and cg.allele2 == "b"          # names preserved
        assert cg.allele1_id is not None                         # identity synthesised/aligned


LONG_CSV = (
    "sample,population,study,marker,allele1,allele1_seq,allele2,allele2_seq\n"
    "W-1,Din,2025,M1,12,AAAACCCCGGGG,14,AAAACCCCGGGGTT\n"
    "W-1,Din,2025,M2,10,AAAA,,\n"          # homozygote (no allele2)
    "W-2,Din,2025,M1,12,AAAACCCCGGGG,14,AAAACCCCGGGGTT\n"   # identical sequences -> same allele id
)


def test_long_csv_with_sequences(client, admin_token):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Long", owner_user_id=u.id)
        db.add(proj); db.flush(); pid = proj.id
        summary = porting.import_genotypes(db, pid, LONG_CSV)   # dispatcher -> long importer
        db.commit()
    assert summary == {"samples": 2, "consensus": 3, "markers": 2}

    with SessionLocal() as db:
        def cg(name, marker):
            return db.scalar(select(ConsensusGenotype).join(Sample).where(
                Sample.project_id == pid, Sample.name == name, ConsensusGenotype.marker == marker))
        c1 = cg("W-1", "M1")
        # true sequence identity — the real sequence, NOT the synthetic "M1:12"
        assert db.get(ReferenceAllele, c1.allele1_id).sequence == "AAAACCCCGGGG"
        # identical sequences across samples resolve to the SAME allele id (matchable)
        assert c1.allele1_id == cg("W-2", "M1").allele1_id
        # homozygote row: allele2 empty
        m2 = cg("W-1", "M2")
        assert m2.allele1 == "10" and m2.allele2 is None


def test_genepop_and_csv_exports(client, admin_token):
    src_id, _ = _seed()
    with SessionLocal() as db:
        gp = porting.genepop(db, src_id)
        meta = porting.metadata_csv(db, src_id)
        animals = porting.animals_csv(db, src_id)
    assert gp.startswith("STReamGT export") and "Pop" in gp and "M1" in gp
    assert "quality_index" in meta and "W1" in meta
    assert "A1" in animals and "members" in animals
