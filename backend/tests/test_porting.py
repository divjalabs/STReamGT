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


def test_is_fixed_survives_json_migration(client, admin_token):
    src_id, owner = _seed()
    with SessionLocal() as db:
        db.query(ReferenceAllele).filter(
            ReferenceAllele.project_id == src_id,
            ReferenceAllele.marker == "M1", ReferenceAllele.sequence == "M1a").update(
            {"is_fixed": True})
        db.commit()
        data = porting.project_json(db, src_id)
    assert any(r["is_fixed"] for r in data["reference_alleles"])   # exported

    with SessionLocal() as db:
        nid = porting.import_project_json(db, owner, data).id
        db.commit()
    with SessionLocal() as db:
        pinned = db.scalar(select(ReferenceAllele).where(
            ReferenceAllele.project_id == nid, ReferenceAllele.sequence == "M1a"))
        other = db.scalar(select(ReferenceAllele).where(
            ReferenceAllele.project_id == nid, ReferenceAllele.sequence == "M1b"))
        assert pinned.is_fixed is True and other.is_fixed is False


def test_genotypes_csv_export(client, admin_token):
    src_id, _ = _seed()
    with SessionLocal() as db:
        csv_text = porting.genotypes_csv(db, src_id)
    assert "M1_1" in csv_text and "M1_2" in csv_text and "W1" in csv_text


def test_genepop_and_csv_exports(client, admin_token):
    src_id, _ = _seed()
    with SessionLocal() as db:
        gp = porting.genepop(db, src_id)
        meta = porting.metadata_csv(db, src_id)
        animals = porting.animals_csv(db, src_id)
    assert gp.startswith("STReamGT export") and "Pop" in gp and "M1" in gp
    assert "quality_index" in meta and "W1" in meta
    assert "A1" in animals and "members" in animals
