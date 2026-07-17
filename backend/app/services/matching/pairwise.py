"""Sequence-level pairwise comparison of two consensus genotypes.

A genotype at a marker is a set of allele identities (reference_alleles ids == sequences):
  size 2 = heterozygote, size 1 = homozygote, empty = missing/not typed.

Per shared marker we classify the pair into a MisBase MatchCode, then accumulate the counts and
the PI/PIsib products that the decision gates consume. Comparison is on allele identity (sequence),
never on the display name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import MatchCode

# Genotype: marker -> frozenset of allele ids. A whole sample is a dict of these.
Genotype = dict


def compare_marker(rset: frozenset, sset: frozenset) -> MatchCode:
    """Classify one marker. rset/sset are allele-id sets (1=homozygote, 2=het, empty=missing).

    Reproduces the MisBase 4-bit table via set logic:
      match, pADO1 (dropout in ref), pADO2 (dropout in search), pADOh (hom vs hom),
      ic1 (one incompatible allele), ic2 (both incompatible), na1/na2 (missing).
    """
    if not rset:
        return MatchCode.na1
    if not sset:
        return MatchCode.na2
    if rset == sset:
        return MatchCode.match
    inter = rset & sset
    if len(rset) == 2 and len(sset) == 1 and sset < rset:
        return MatchCode.pADO2                       # AB : AA  (search dropped an allele)
    if len(rset) == 1 and len(sset) == 2 and rset < sset:
        return MatchCode.pADO1                       # AA : AB  (ref dropped an allele)
    if len(rset) == 1 and len(sset) == 1:
        return MatchCode.pADOh                       # AA : BB  (ambiguous homozygote dropout)
    if len(inter) == 1:
        return MatchCode.ic1                         # AB : AC  (one incompatible allele)
    return MatchCode.ic2                             # AB : CD / AB : CC / AA : BC (both incompatible)


_ADO = {MatchCode.pADO1, MatchCode.pADO2, MatchCode.pADOh}


@dataclass
class PairResult:
    loci_compared: int = 0        # markers with data in both samples (post-exclusion)
    loci_matched: int = 0         # same as loci_compared here (NA markers excluded)
    num_ado_mm: int = 0
    num_1ic: int = 0
    num_2ic: int = 0
    num_total_ic: int = 0         # hard incompatibilities = 1IC + 2IC
    flat_mismatch: int = 0        # allele-level mismatch count (Pirog metric)
    d_pi: float = 1.0             # product of per-marker PID over matched loci (1.0 if PI off)
    d_pi_sib: float = 1.0
    codes: dict = field(default_factory=dict)


def compare(ref: Genotype, search: Genotype, *, excluded: set | None = None,
            pi_by_marker: dict | None = None, use_pi: bool = False) -> PairResult:
    """Compare two samples' genotypes across their shared, non-excluded markers."""
    excluded = excluded or set()
    res = PairResult()
    markers = (set(ref) | set(search)) - excluded
    for marker in markers:
        rset = ref.get(marker) or frozenset()
        sset = search.get(marker) or frozenset()
        code = compare_marker(rset, sset)
        if code in (MatchCode.na1, MatchCode.na2):
            continue                                 # missing data: not a mismatch, not counted
        res.codes[marker] = code
        res.loci_compared += 1
        res.loci_matched += 1
        if code in _ADO:
            res.num_ado_mm += 1
            res.flat_mismatch += 1
        elif code == MatchCode.ic1:
            res.num_1ic += 1
            res.flat_mismatch += 1
        elif code == MatchCode.ic2:
            res.num_2ic += 1
            res.flat_mismatch += 2
        if use_pi and pi_by_marker is not None:
            pid, pidsib = pi_by_marker.get(marker, (1.0, 1.0))
            res.d_pi *= pid
            res.d_pi_sib *= pidsib
    res.num_total_ic = res.num_1ic + res.num_2ic
    return res
