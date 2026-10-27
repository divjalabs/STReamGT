"""Sample-level QC (M4): discard-QC gates + sex determination, run after consensus.

Thresholds are the MisBase production values (docs/consensus-db-vs-pipeline.md). Kept as module
constants for now; per-project overrides can be added later. Both steps respect manual locks
(sex_locked) and never touch a user's explicit discard flag except to compute genotype_ok.
"""
from __future__ import annotations

import difflib
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Sample, ConsensusGenotype, ReplicateObservation, ReplicateAmplification, Sex, Kit,
)
from app.models.enums import PrimerType

# --- discard-QC gates (MisBase stblSettings) ---
MIN_QUALITY_INDEX = 0.1        # MinQualityIndex
MIN_AVG_SUCCESS_RATE = 10.0    # MinAverageSuccessRate (percent)
MIN_NUM_REPLICATES = 2         # MinNumOfReplicates

# --- sex determination (data-driven from the panel's SNP sex markers) ---
POS_MIN_AMPS = 1               # min Y-positive wells to call male
NEG_MIN_AMPS = 2               # min sex-locus amplifications to trust a female call
NEG_MIN_OTHER_LOCI = 2         # successful other loci supporting a female call


def _sex_refs(primer) -> list[tuple[str, str]]:
    """(role, ref_seq) list for a sex-SNP primer; role in {'X','Y'} (uppercased).

    Reads the `X:<seq>/Y:<seq>` form from `primer.sequence` (single-locus carries both, a
    separate-locus row carries one). Falls back to inferring the chromosome from the locus name
    (ZFY/…Y/SRY -> Y; ZFX/…X -> X) when the sequence has no `name:` prefix.
    """
    seq = (primer.sequence or "").strip()
    refs: list[tuple[str, str]] = []
    if ":" in seq:
        for item in seq.split("/"):
            if ":" not in item:
                continue
            name, s = item.split(":", 1)
            role, s = name.strip().upper()[:1], s.strip()
            if role in ("X", "Y") and s:
                refs.append((role, s.upper()))
    if not refs and seq:
        name = (primer.locus or "").upper()
        role = "Y" if ("ZFY" in name or "SRY" in name or name.endswith("Y")) else \
               ("X" if ("ZFX" in name or name.endswith("X")) else None)
        if role:
            refs.append((role, seq.upper()))
    return refs


def _nearest_role(obs_seq: str | None, refs: list[tuple[str, str]]) -> str | None:
    """Role of the reference most similar to `obs_seq` (case-insensitive); None if no refs."""
    o = (obs_seq or "").upper()
    best_role, best = None, -1.0
    for role, ref in refs:
        r = difflib.SequenceMatcher(None, o, ref).ratio()
        if r > best:
            best, best_role = r, role
    return best_role


def sex_markers(db: Session, sample: Sample) -> dict[str, list[tuple[str, str]]]:
    """{locus: [(role, ref_seq)]} for the sample's panel SNP sex markers (empty if none)."""
    kit = db.get(Kit, sample.kit_id) if sample.kit_id else None
    panel = kit.panel if kit else None
    out: dict[str, list[tuple[str, str]]] = {}
    for p in (panel.primers if panel else []):
        if p.type == PrimerType.snp:
            refs = _sex_refs(p)
            if refs:
                out[p.locus] = refs
    return out


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


def determine_sex(db: Session, sample: Sample) -> None:
    """Data-driven call from the panel's SNP sex markers: a called allele resolving to a Y
    reference -> male; only X (with enough amplification + other typed loci) -> female; else
    unknown. Handles single-locus (X:/Y: on one row) and separate X/Y loci alike. Skips
    samples whose sex was set/locked by a user."""
    if sample.sex_locked:
        return
    loci = sex_markers(db, sample)
    if not loci:
        sample.sex = Sex.unknown
        return

    y_wells: set = set()
    x_wells: set = set()
    for o in db.scalars(select(ReplicateObservation).where(
            ReplicateObservation.sample_id == sample.id,
            ReplicateObservation.marker.in_(loci.keys()),
            ReplicateObservation.called.is_(True))):
        role = _nearest_role(o.sequence, loci.get(o.marker, []))
        if role == "Y":
            y_wells.add((o.plate, o.position))
        elif role == "X":
            x_wells.add((o.plate, o.position))

    amp_wells = {
        (a.plate, a.position)
        for a in db.scalars(select(ReplicateAmplification).where(
            ReplicateAmplification.sample_id == sample.id,
            ReplicateAmplification.marker.in_(loci.keys())))
    }
    n_other = db.query(ConsensusGenotype).filter(
        ConsensusGenotype.sample_id == sample.id,
        ConsensusGenotype.marker.notin_(loci.keys()),
        ConsensusGenotype.allele1.isnot(None)).count()

    if len(y_wells) >= POS_MIN_AMPS:
        sample.sex = Sex.male
    elif (not y_wells and len(amp_wells) >= NEG_MIN_AMPS
          and (x_wells or n_other >= NEG_MIN_OTHER_LOCI)):
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
