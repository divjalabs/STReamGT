"""Project-scoped reference-allele naming.

Names alleles `Length[_Variant]` by frequency, mirroring the legacy MisBase `NameNGSAlleles`: within
each (marker, length) group the most-read sequence gets the bare `Length`, the rest get `Length_N`.
Frequency = project-wide accumulated reads per (marker, sequence). Curated (is_fixed) names are reserved
and never auto-renamed; the ranker skips their names. Renames are propagated to the denormalized display
names on replicate observations and consensus rows — a pure relabel (identities/calls unchanged).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from app.models import (
    Sample, ReplicateObservation, ConsensusGenotype, ReferenceAllele,
)


def project_read_totals(db: Session, project_id: int) -> dict[tuple[str, str], int]:
    """Accumulated read count per (marker, sequence) across all of the project's samples (MisBase NReads)."""
    rows = db.execute(
        select(ReplicateObservation.marker, ReplicateObservation.sequence,
               func.sum(ReplicateObservation.read_count))
        .join(Sample, Sample.id == ReplicateObservation.sample_id)
        .where(Sample.project_id == project_id, ReplicateObservation.sequence.is_not(None))
        .group_by(ReplicateObservation.marker, ReplicateObservation.sequence)
    ).all()
    return {(m, s): int(t or 0) for m, s, t in rows}


def _length_of(allele: ReferenceAllele) -> int:
    return allele.length if allele.length is not None else len(allele.sequence or "")


def renormalize_allele_names(db: Session, project_id: int,
                             fixed_names: dict[int, str] | None = None) -> dict:
    """Re-derive names for all non-fixed alleles by frequency, reserving fixed names, then propagate.

    fixed_names: optional {reference_allele_id: name} to pin first (marks those is_fixed=True).
    Returns {"alleles": total, "renamed": n_changed}.
    """
    totals = project_read_totals(db, project_id)
    alleles = list(db.scalars(
        select(ReferenceAllele).where(ReferenceAllele.project_id == project_id)))
    old_names = {a.id: a.allele_name for a in alleles}       # captured before any change, so fixed renames propagate too
    if fixed_names:
        for a in alleles:
            if a.id in fixed_names:
                a.allele_name, a.is_fixed = fixed_names[a.id], True

    groups: dict[tuple[str, int], list[ReferenceAllele]] = defaultdict(list)
    for a in alleles:
        a.n = totals.get((a.marker, a.sequence), a.n)   # keep n as the project-wide total
        groups[(a.marker, _length_of(a))].append(a)

    for (_marker, length), group in groups.items():
        reserved = {a.allele_name for a in group if a.is_fixed and a.allele_name}
        non_fixed = sorted(
            (a for a in group if not a.is_fixed),
            key=lambda a: (-(totals.get((a.marker, a.sequence)) or 0), a.sequence or ""))
        v = 0
        for a in non_fixed:
            while True:                                  # lowest variant whose name isn't taken by a fixed allele
                v += 1
                name = str(length) if v == 1 else f"{length}_{v}"
                if name not in reserved:
                    break
            a.allele_name, a.variant = name, v
            reserved.add(name)
    db.flush()

    changes = {a.id: (old_names[a.id], a.allele_name)
               for a in alleles if old_names[a.id] != a.allele_name}
    _propagate_rename(db, project_id, alleles, changes)
    return {"alleles": len(alleles), "renamed": len(changes)}


def _propagate_rename(db: Session, project_id: int,
                      alleles: list[ReferenceAllele], changes: dict[int, tuple[str, str]]) -> None:
    """Relabel the denormalized display names wherever a renamed allele appears (calls untouched)."""
    if not changes:
        return
    by_id = {a.id: a for a in alleles}
    project_sample_ids = select(Sample.id).where(Sample.project_id == project_id)

    for aid, (_old, new) in changes.items():
        a = by_id[aid]
        # per-observation name (used by a future Rerun consensus)
        db.execute(
            update(ReplicateObservation)
            .where(ReplicateObservation.sample_id.in_(project_sample_ids),
                   ReplicateObservation.marker == a.marker,
                   ReplicateObservation.sequence == a.sequence)
            .values(allele_name=new))
        # consensus display names, matched by the sequence-backed FK (safe on locked/edited rows)
        for k in (1, 2, 3, 4):
            db.execute(
                update(ConsensusGenotype)
                .where(getattr(ConsensusGenotype, f"allele{k}_id") == aid)
                .values(**{f"allele{k}": new}))

    # confirmed/unconfirmed are ';'-joined name strings (not FK-linked) — token-remap per marker.
    rename_by_marker: dict[str, dict[str, str]] = defaultdict(dict)
    for aid, (old, new) in changes.items():
        rename_by_marker[by_id[aid].marker][old] = new
    cons = db.scalars(
        select(ConsensusGenotype)
        .join(Sample, Sample.id == ConsensusGenotype.sample_id)
        .where(Sample.project_id == project_id)).all()
    for c in cons:
        remap = rename_by_marker.get(c.marker)
        if not remap:
            continue
        for field in ("confirmed_alleles", "unconfirmed_alleles"):
            val = getattr(c, field) or ""
            if not val:
                continue
            toks = val.split(";")
            new_toks = [remap.get(t, t) for t in toks]
            if new_toks != toks:
                setattr(c, field, ";".join(new_toks))
    db.flush()
