"""The pairwise match-code table (sequence-level) and the two-tier decision gates."""
from types import SimpleNamespace

from app.models.enums import MatchCode, MatchTier, MismatchMetric
from app.services.matching.pairwise import compare_marker, compare
from app.services.matching.decision import classify

A, B, C, D = 1, 2, 3, 4          # allele identities (reference_alleles ids)
fs = frozenset


def test_match_code_table():
    assert compare_marker(fs({A}), fs({A})) == MatchCode.match          # AA:AA
    assert compare_marker(fs({A, B}), fs({A, B})) == MatchCode.match    # AB:AB
    assert compare_marker(fs({A, B}), fs({A})) == MatchCode.pADO2       # AB:AA dropout in search
    assert compare_marker(fs({A}), fs({A, B})) == MatchCode.pADO1       # AA:AB dropout in ref
    assert compare_marker(fs({A}), fs({B})) == MatchCode.pADOh          # AA:BB hom vs hom
    assert compare_marker(fs({A, B}), fs({A, C})) == MatchCode.ic1      # AB:AC one incompatible
    assert compare_marker(fs({A, B}), fs({C, D})) == MatchCode.ic2      # AB:CD both incompatible
    assert compare_marker(fs({A, B}), fs({C})) == MatchCode.ic2         # AB:CC
    assert compare_marker(fs({A}), fs({B, C})) == MatchCode.ic2         # AA:BC
    assert compare_marker(fs(), fs({A})) == MatchCode.na1               # missing ref
    assert compare_marker(fs({A}), fs()) == MatchCode.na2               # missing search


def test_compare_accumulates():
    # 3 matches, 1 ADO, 1 one-IC, 1 two-IC, 1 missing (not counted)
    ref = {"m1": fs({A, B}), "m2": fs({A}), "m3": fs({C, D}), "m4": fs({A, B}),
           "m5": fs({A, B}), "m6": fs({A, B}), "m7": fs({A})}
    sea = {"m1": fs({A, B}), "m2": fs({A}), "m3": fs({C, D}), "m4": fs({A}),      # ADO
           "m5": fs({A, C}), "m6": fs({C, D}), "m7": fs()}                          # 1IC, 2IC, missing
    r = compare(ref, sea)
    assert r.loci_matched == 6                     # m7 (missing) excluded
    assert r.num_ado_mm == 1 and r.num_1ic == 1 and r.num_2ic == 1
    assert r.num_total_ic == 2                      # 1IC + 2IC
    assert r.flat_mismatch == 1 + 1 + 2            # ADO=1, 1IC=1, 2IC=2
    assert r.d_pi == 1.0                            # PI off


def test_excluded_and_pi():
    ref = {"m1": fs({A, B}), "m2": fs({A, B})}
    sea = {"m1": fs({A, B}), "m2": fs({A, B})}
    r = compare(ref, sea, excluded={"m2"}, use_pi=True,
                pi_by_marker={"m1": (0.01, 0.1), "m2": (0.01, 0.1)})
    assert r.loci_matched == 1                      # m2 excluded
    assert abs(r.d_pi - 0.01) < 1e-9                # only m1 contributes


def _settings(**over):
    base = dict(min_shared_loci=12, mismatch_metric=MismatchMetric.decomposed,
                use_pi_gate=False,
                max_ado_mm_match=4, max_1ic_match=2, max_2ic_match=2, max_total_mm_match=4,
                reliable_max_ado_mm=2, reliable_max_1ic=0, reliable_max_2ic=0, reliable_max_total=2,
                tm_possible=4, tm_reliable=2,
                pi_max=5e-4, pisib_max=1e-2, reliable_pi_max=1e-5, reliable_pisib_max=5e-3)
    base.update(over)
    return SimpleNamespace(**base)


def test_decision_min_loci():
    r = compare({f"m{i}": fs({A, B}) for i in range(10)},
                {f"m{i}": fs({A, B}) for i in range(10)})   # only 10 shared < 12
    assert classify(r, _settings()) == MatchTier.none


def _identical(n=14):
    g = {f"m{i}": fs({A, B}) for i in range(n)}
    return compare(g, dict(g))


def test_decision_decomposed_tiers():
    assert classify(_identical(), _settings()) == MatchTier.reliable      # 0 mismatches
    # one 1IC: within possible (max_1ic_match=2) but not reliable (reliable_max_1ic=0)
    ref = {f"m{i}": fs({A, B}) for i in range(14)}
    sea = dict(ref); sea["m0"] = fs({A, C})
    assert classify(compare(ref, sea), _settings()) == MatchTier.possible


def test_decision_flat_and_pi():
    ref = {f"m{i}": fs({A, B}) for i in range(14)}
    sea = dict(ref); sea["m0"] = fs({A, C})          # flat_mismatch = 1
    assert classify(compare(ref, sea), _settings(mismatch_metric=MismatchMetric.flat)) == MatchTier.reliable
    # PI gate downgrades when the shared genotype is too common (d_pi above threshold)
    pi = {f"m{i}": (0.9, 0.95) for i in range(14)}   # d_pi huge -> fails PI
    r = compare(ref, dict(ref), use_pi=True, pi_by_marker=pi)
    assert classify(r, _settings(use_pi_gate=True)) == MatchTier.none
