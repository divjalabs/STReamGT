"""Two-tier match decision from a PairResult and a settings row.

Layered gates: (1) minimum shared loci (always); (2) mismatch thresholds — flat allele-mismatch
Tm (Pirog) or the MisBase ADO/1IC/2IC/total decomposition; (3) optional PI/PIsib (Waits 2001).
Returns MatchTier: none < possible < reliable.
"""
from __future__ import annotations

from app.models.enums import MatchTier, MismatchMetric
from app.services.matching.pairwise import PairResult


def classify(pair: PairResult, s) -> MatchTier:
    """`s` is a MatchingSettings row (or any object with the same attributes)."""
    if pair.loci_matched < s.min_shared_loci:
        return MatchTier.none

    if s.mismatch_metric == MismatchMetric.flat:
        possible = pair.flat_mismatch <= s.tm_possible
        reliable = pair.flat_mismatch <= s.tm_reliable
    else:  # decomposed (MisBase)
        possible = (
            pair.num_ado_mm <= s.max_ado_mm_match
            and pair.num_1ic <= s.max_1ic_match
            and pair.num_2ic <= s.max_2ic_match
            and pair.num_total_ic <= s.max_total_mm_match
        )
        reliable = (
            pair.num_ado_mm <= s.reliable_max_ado_mm
            and pair.num_1ic <= s.reliable_max_1ic
            and pair.num_2ic <= s.reliable_max_2ic
            and pair.num_total_ic <= s.reliable_max_total
        )

    if s.use_pi_gate:
        possible = possible and pair.d_pi <= s.pi_max and pair.d_pi_sib <= s.pisib_max
        reliable = reliable and pair.d_pi <= s.reliable_pi_max and pair.d_pi_sib <= s.reliable_pisib_max

    if possible and reliable:
        return MatchTier.reliable
    if possible:
        return MatchTier.possible
    return MatchTier.none
