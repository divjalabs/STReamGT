"""M4: discard-QC gates (genotype_ok) and data-driven sex determination (panel SNP markers)."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Sample, ConsensusGenotype,
    ReplicateAmplification, ReplicateObservation, Sex, Kit, PrimerPanel, Primer, PrimerType,
)
from app.services.qc import run_sample_qc


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


def _sex_kit(db, snp_rows, suffix):
    """Panel with the given SNP sex rows [(locus, sequence)] + a kit on it. Returns the kit."""
    panel = PrimerPanel(code=f"SEXP_{suffix}")
    db.add(panel); db.flush()
    for locus, seq in snp_rows:
        db.add(Primer(panel_id=panel.id, locus=locus, type=PrimerType.snp, sequence=seq))
    kit = Kit(kit_code=f"SEXK_{suffix}", panel_id=panel.id)
    db.add(kit); db.flush()
    return kit


def _amps(db, sample, marker, wells):
    for w in wells:
        db.add(ReplicateAmplification(sample_id=sample.id, marker=marker, plate=w, position=1))


def _called(db, sample, marker, plate, seq):
    db.add(ReplicateObservation(sample_id=sample.id, marker=marker, plate=plate, position=1,
                                read_count=300, length=len(seq), called=True, flag="", sequence=seq))


def test_sex_single_locus(client, admin_token):
    """One SNP locus, same primers: sequence 'X:<seq>/Y:<seq>'."""
    with SessionLocal() as db:
        proj, pop = _ctx(db)
        kit = _sex_kit(db, [("UA_ZF", "X:AAAACCCC/Y:AAATCCCC")], "single")

        male = _sample(db, proj, pop, kit_id=kit.id)
        _amps(db, male, "UA_ZF", ["PP1", "PP2"])
        _called(db, male, "UA_ZF", "PP1", "AAATCCCC")     # nearest Y -> male

        female = _sample(db, proj, pop, kit_id=kit.id)
        _amps(db, female, "UA_ZF", ["PP1", "PP2"])
        _called(db, female, "UA_ZF", "PP1", "AAAACCCC")   # nearest X, no Y -> female

        unknown = _sample(db, proj, pop, kit_id=kit.id)   # sex panel but no sex-locus data
        locked = _sample(db, proj, pop, kit_id=kit.id, sex=Sex.male, sex_locked=True)
        _amps(db, locked, "UA_ZF", ["PP1", "PP2"]); _called(db, locked, "UA_ZF", "PP1", "AAAACCCC")
        db.commit()

        run_sample_qc(db, [male.id, female.id, unknown.id, locked.id]); db.commit()
        for s in (male, female, unknown, locked): db.refresh(s)
        assert male.sex == Sex.male
        assert female.sex == Sex.female
        assert unknown.sex == Sex.unknown
        assert locked.sex == Sex.male                     # sex_locked -> untouched


def test_sex_two_loci_wolf(client, admin_token):
    """Separate X/Y loci (different primers): ZFX_NEW='X:<seq>', ZFY_NEW='Y:<seq>'."""
    with SessionLocal() as db:
        proj, pop = _ctx(db)
        kit = _sex_kit(db, [("ZFX_NEW", "X:GGGGAAAA"), ("ZFY_NEW", "Y:TTTTCCCC")], "wolf")

        male = _sample(db, proj, pop, kit_id=kit.id)
        _amps(db, male, "ZFX_NEW", ["PP1", "PP2"]); _amps(db, male, "ZFY_NEW", ["PP1", "PP2"])
        _called(db, male, "ZFX_NEW", "PP1", "GGGGAAAA")
        _called(db, male, "ZFY_NEW", "PP1", "TTTTCCCC")   # Y locus produced an allele -> male

        female = _sample(db, proj, pop, kit_id=kit.id)
        _amps(db, female, "ZFX_NEW", ["PP1", "PP2"]); _amps(db, female, "ZFY_NEW", ["PP1", "PP2"])
        _called(db, female, "ZFX_NEW", "PP1", "GGGGAAAA")  # X only, Y silent -> female
        db.commit()

        run_sample_qc(db, [male.id, female.id]); db.commit()
        db.refresh(male); db.refresh(female)
        assert male.sex == Sex.male
        assert female.sex == Sex.female
