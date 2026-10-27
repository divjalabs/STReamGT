"""Group samples into individual animals (subgroups) from reliable matches.

Reference-anchored (MisBase primary): the best sample anchors a subgroup, and a sample joins the
subgroup whose reference it reliably matches. Reference priority: IsAnimalReference, then
GenotypeOK, then QualityIndex. Star-shaped (chaining-proof around each reference) and
incremental-friendly. The batch maximal-clique method (clique_qc.py) is a QC cross-check.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SampleMeta:
    sample_id: int
    is_animal_reference: bool = False
    genotype_ok: bool = False
    quality_index: float | None = None


@dataclass
class Subgroup:
    reference: int
    members: list = field(default_factory=list)


def _priority(m: SampleMeta):
    # higher is better: reference type, then genotyped-ok, then quality index
    return (1 if m.is_animal_reference else 0,
            1 if m.genotype_ok else 0,
            m.quality_index if m.quality_index is not None else -1.0)


def reference_anchored(metas: list[SampleMeta], reliable_pairs: set) -> list[Subgroup]:
    """reliable_pairs: set of frozenset({sample_a, sample_b}) that are RELIABLE matches."""
    ordered = sorted(metas, key=_priority, reverse=True)
    subgroups: list[Subgroup] = []
    for m in ordered:
        joined = None
        for sg in subgroups:                         # references are highest-priority-first
            if frozenset((m.sample_id, sg.reference)) in reliable_pairs:
                joined = sg
                break
        if joined is None:
            subgroups.append(Subgroup(reference=m.sample_id, members=[m.sample_id]))
        else:
            joined.members.append(m.sample_id)
    return subgroups
