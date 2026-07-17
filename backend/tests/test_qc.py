"""M4: discard-QC gates (genotype_ok) and SRY-style sex determination."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Sample, ConsensusGenotype,
    ReplicateAmplification, ReplicateObservation, Sex,
)
from app.services.qc import run_sample_qc, SEX_MARKER


def _ctx(db):
    u = db.scalar(select(User).where(User.email == "admin@x.com"))
    proj = Project(public_id=uuid.uuid4().hex, name="P" + uuid.uuid4().hex[:6], owner_user_id=u.id)
    db.add(proj); db.flush()
    pop = Population(project_id=proj.id, name="Pop"); db.add(pop); db.flush()
    return proj, pop


def _sample(db, proj, pop, **kw):
    s = Sample(public_id=uuid.uuid4().hex, system_code="S-" + uuid.uuid4().hex[:6],
               project_id=proj.id, population_id=pop.id, name="w", **kw)
    db.add(s); db.flush()
    return s


def test_qc_gates(client, admin_token):
    with SessionLocal() as db:
        proj, pop = _ctx(db)
        good = _sample(db, proj, pop)
        for m in ("M1", "M2", "M3"):
            db.add(ConsensusGenotype(sample_id=good.id, marker=m, allele1="12",
                                     quality_index=0.8, success_rate=90.0, n_amp=4))
        bad = _sample(db, proj, pop)
        for m in ("M1", "M2"):
            db.add(ConsensusGenotype(sample_id=bad.id, marker=m, allele1="12",
                                     quality_index=0.05, success_rate=5.0, n_amp=1))
        db.commit()
        run_sample_qc(db, [good.id, bad.id]); db.commit()
        db.refresh(good); db.refresh(bad)
        assert good.genotype_ok is True
        assert abs(good.quality_index - 0.8) < 1e-6 and good.n_replicates == 4
        assert bad.genotype_ok is False           # QI 0.05 < 0.1, success 5% < 10%, 1 rep < 2


def _sry_amps(db, sample, wells):
    for w in wells:
        db.add(ReplicateAmplification(sample_id=sample.id, marker=SEX_MARKER, plate=w, position=1))


def test_sex_determination(client, admin_token):
    with SessionLocal() as db:
        proj, pop = _ctx(db)

        male = _sample(db, proj, pop)
        _sry_amps(db, male, ["PP1", "PP2"])
        db.add(ReplicateObservation(sample_id=male.id, marker=SEX_MARKER, plate="PP1", position=1,
                                    read_count=300, length=90, called=True, flag="", sequence="Y"))

        female = _sample(db, proj, pop)
        _sry_amps(db, female, ["PP1", "PP2"])       # amplified but never called (negative)
        for m in ("M1", "M2"):                       # enough other loci succeeded
            db.add(ConsensusGenotype(sample_id=female.id, marker=m, allele1="12"))

        unknown = _sample(db, proj, pop)             # no sex-marker amplifications at all

        locked = _sample(db, proj, pop, sex=Sex.male, sex_locked=True)
        _sry_amps(db, locked, ["PP1", "PP2"])        # female-like data, but locked
        db.commit()

        run_sample_qc(db, [male.id, female.id, unknown.id, locked.id]); db.commit()
        for s in (male, female, unknown, locked):
            db.refresh(s)
        assert male.sex == Sex.male                  # SRY seen
        assert female.sex == Sex.female              # SRY absent + other loci typed
        assert unknown.sex == Sex.unknown
        assert locked.sex == Sex.male                # sex_locked -> untouched
