"""Sample-level QC (M4): discard-QC gates + sex determination, run after consensus.

Thresholds are the MisBase production values (docs/consensus-db-vs-pipeline.md). Kept as module
constants for now; per-project overrides can be added later. Both steps respect manual locks
(sex_locked) and never touch a user's explicit discard flag except to compute genotype_ok.
"""
from __future__ import annotations

from statistics import fmean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Sample, ConsensusGenotype, ReplicateObservation, ReplicateAmplification, Sex,
)

# --- discard-QC gates (MisBase stblSettings) ---
MIN_QUALITY_INDEX = 0.1        # MinQualityIndex
MIN_AVG_SUCCESS_RATE = 10.0    # MinAverageSuccessRate (percent)
MIN_NUM_REPLICATES = 2         # MinNumOfReplicates

# --- sex determination (MisBase SRY-style Y-marker) ---
SEX_MARKER = "SRY"             # Y-chromosome marker: present -> male
POS_MIN_AMPS = 1               # NumAmpsPositiveSexSRY
NEG_MIN_AMPS = 2               # NumAmpsNegativeSexSRY
NEG_MIN_OTHER_LOCI = 2         # NumSuccPCRAmpsNegativeSexSRY (successful other loci for a female call)


def apply_qc(db: Session, sample: Sample) -> None:
    """Aggregate the sample's consensus into QC metrics and set genotype_ok."""
    cons = db.scalars(select(ConsensusGenotype).where(
        ConsensusGenotype.sample_id == sample.id)).all()
    typed = [c for c in cons if c.allele1]                      # markers with a called genotype
    qis = [c.quality_index for c in typed if c.quality_index is not None]
    srs = [c.success_rate for c in typed if c.success_rate is not None]
    mean_qi = fmean(qis) if qis else 0.0
    mean_sr = fmean(srs) if srs else 0.0
    n_amps = max((c.n_amp or 0 for c in cons), default=0)

    sample.quality_index = round(mean_qi, 4)
    sample.n_replicates = n_amps
    sample.genotype_ok = bool(
        typed and mean_qi >= MIN_QUALITY_INDEX
        and mean_sr >= MIN_AVG_SUCCESS_RATE
        and n_amps >= MIN_NUM_REPLICATES
    )


def determine_sex(db: Session, sample: Sample, marker: str = SEX_MARKER) -> None:
    """SRY-style call: Y-marker seen -> male; consistently absent with enough other typed loci
    -> female; else unknown. Skips samples whose sex was set/locked by a user."""
    if sample.sex_locked:
        return
    amps = db.scalars(select(ReplicateAmplification).where(
        ReplicateAmplification.sample_id == sample.id,
        ReplicateAmplification.marker == marker)).all()
    if not amps:
        sample.sex = Sex.unknown
        return
    # wells where the sex marker produced a called allele = positive amplifications
    pos_keys = {
        (o.plate, o.position)
        for o in db.scalars(select(ReplicateObservation).where(
            ReplicateObservation.sample_id == sample.id,
            ReplicateObservation.marker == marker,
            ReplicateObservation.called.is_(True)))
    }
    n_amps = len({(a.plate, a.position) for a in amps})
    n_pos = len(pos_keys)
    n_neg = n_amps - n_pos
    n_other = db.query(ConsensusGenotype).filter(
        ConsensusGenotype.sample_id == sample.id,
        ConsensusGenotype.marker != marker,
        ConsensusGenotype.allele1.isnot(None)).count()

    if n_pos >= POS_MIN_AMPS:
        sample.sex = Sex.male
    elif n_neg >= NEG_MIN_AMPS and n_other >= NEG_MIN_OTHER_LOCI:
        sample.sex = Sex.female
    else:
        sample.sex = Sex.unknown


def run_sample_qc(db: Session, sample_ids) -> int:
    """Apply QC gates + sex determination to each sample. Returns count processed."""
    n = 0
    for sid in sample_ids:
        sample = db.get(Sample, sid)
        if sample is None:
            continue
        if sample.is_control:   # controls aren't scored (kept out of n_replicates/genotype_ok)
            continue
        apply_qc(db, sample)
        determine_sex(db, sample)
        n += 1
    db.flush()
    return n
