"""Backend consensus service: recompute from stored replicate data, and edit / lock genotypes.

Recompute is sequence-level (via consensus_core) and NEVER touches locked rows. Edits and locks
are audited in consensus_edit_log. Thresholds default to the production values (2/2); a later
milestone can source them from matching_settings.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Sample, ReplicateObservation, ReplicateAmplification, ConsensusGenotype, ConsensusEditLog,
    ReferenceAllele, ConsensusSource,
)
from app.services.consensus_core import Obs, compute_consensus, ConsensusResult

# Editable display fields on a consensus genotype (the allele calls).
EDITABLE_ALLELES = ("allele1", "allele2", "allele3", "allele4")


def _ref_id_cache(db: Session, project_id: int):
    cache: dict[tuple[str, str], int | None] = {}

    def lookup_by_seq(marker: str, sequence: str) -> int | None:
        key = ("seq", marker, sequence)
        if key not in cache:
            cache[key] = db.scalar(select(ReferenceAllele.id).where(
                ReferenceAllele.project_id == project_id,
                ReferenceAllele.marker == marker,
                ReferenceAllele.sequence == sequence,
            ))
        return cache[key]

    def lookup_by_name(marker: str, name: str) -> int | None:
        key = ("name", marker, name)
        if key not in cache:
            cache[key] = db.scalar(select(ReferenceAllele.id).where(
                ReferenceAllele.project_id == project_id,
                ReferenceAllele.marker == marker,
                ReferenceAllele.allele_name == name,
            ))
        return cache[key]

    return lookup_by_seq, lookup_by_name


def recompute(db: Session, sample_ids, *, thr_homo: int = 2, thr_hetero: int = 2) -> int:
    """Recompute consensus for the given samples from their replicate rows. Returns rows written.
    Locked (sample, marker) rows are left untouched."""
    written = 0
    for sid in sample_ids:
        sample = db.get(Sample, sid)
        if sample is None:
            continue
        by_seq, _by_name = _ref_id_cache(db, sample.project_id)

        obs_by_marker: dict[str, list[Obs]] = defaultdict(list)
        for o in db.scalars(select(ReplicateObservation).where(
                ReplicateObservation.sample_id == sid, ReplicateObservation.called.is_(True))):
            if not o.sequence:
                continue
            obs_by_marker[o.marker].append(Obs(
                key=o.sequence, name=o.allele_name or o.sequence, flag=o.flag or "",
                plate=o.plate, position=o.position, read_count=o.read_count,
            ))
        amps_by_marker: dict[str, set] = defaultdict(set)
        for a in db.scalars(select(ReplicateAmplification).where(
                ReplicateAmplification.sample_id == sid)):
            amps_by_marker[a.marker].add((a.plate, a.position))

        for marker in set(obs_by_marker) | set(amps_by_marker):
            obs = obs_by_marker.get(marker, [])
            amp_count = len(amps_by_marker.get(marker)
                            or {(o.plate, o.position) for o in obs})
            res = compute_consensus(obs, amp_count, thr_homo, thr_hetero)

            row = db.scalar(select(ConsensusGenotype).where(
                ConsensusGenotype.sample_id == sid, ConsensusGenotype.marker == marker))
            if row is not None and row.is_locked:
                continue                                # preserve locked genotypes
            if row is None:
                row = ConsensusGenotype(sample_id=sid, marker=marker)
                db.add(row)
            _apply(row, res, marker, by_seq)
            written += 1
    db.flush()
    from app.services.qc import run_sample_qc      # QC gates + sex, post-consensus
    run_sample_qc(db, list(sample_ids))
    return written


def _apply(row: ConsensusGenotype, res: ConsensusResult, marker: str, by_seq) -> None:
    names = (list(res.names.get(k) for k in res.accepted) + [None, None, None, None])[:4]
    ids = (list(by_seq(marker, k) for k in res.accepted) + [None, None, None, None])[:4]
    row.allele1, row.allele2, row.allele3, row.allele4 = names
    row.allele1_id, row.allele2_id, row.allele3_id, row.allele4_id = ids
    row.ncnf_a1, row.ncnf_a2 = res.ncnf_a1, res.ncnf_a2
    row.confirmed_alleles = ";".join(res.confirmed_names())
    row.unconfirmed_alleles = ";".join(res.unconfirmed_names())
    row.n_amp, row.n_amp_ok = res.n_amp, res.n_amp_ok
    row.success_rate = res.success_rate
    row.ado, row.ado_rate = res.ado, res.ado_rate
    row.quality_index = res.quality_index
    row.false_alleles = res.false_alleles
    row.reads_per_amp = res.reads_per_amp
    row.sd_reads_per_amp = res.sd_reads_per_amp
    row.source = ConsensusSource.recomputed
    row.is_edited = False


def edit_consensus(db: Session, row: ConsensusGenotype, changes: dict, user_id: int) -> ConsensusGenotype:
    """Apply manual allele-call edits, re-resolving the sequence identity, with an audit log."""
    _by_seq, by_name = _ref_id_cache(db, db.get(Sample, row.sample_id).project_id)
    for field, new in changes.items():
        if field not in EDITABLE_ALLELES:
            continue
        old = getattr(row, field)
        new = new or None
        if (old or None) != new:
            db.add(ConsensusEditLog(consensus_id=row.id, user_id=user_id, field=field,
                                    old_value=old, new_value=new))
            setattr(row, field, new)
            # keep the sequence-backed identity in sync with the edited name
            id_field = f"{field}_id"
            setattr(row, id_field, by_name(row.marker, new) if new else None)
    row.is_edited = True
    row.source = ConsensusSource.manual
    row.edited_by = user_id
    row.edited_at = datetime.now(timezone.utc)
    db.flush()
    return row


def set_lock(db: Session, row: ConsensusGenotype, locked: bool, user_id: int) -> ConsensusGenotype:
    if row.is_locked != locked:
        db.add(ConsensusEditLog(consensus_id=row.id, user_id=user_id, field="is_locked",
                                old_value=str(row.is_locked), new_value=str(locked)))
        row.is_locked = locked
    db.flush()
    return row
