"""Parity: consensus_core reproduces pipeline/bin/callConsensus.py output exactly.

Fixture = the same S1 (het 12/14 with a dropout well + a false-allele well) and S2 (homozygote)
case verified against the pipeline, keyed on sequence. Thresholds 2/2 (production).
"""
from app.services.consensus_core import Obs, compute_consensus

A, B, C = "A" * 12, "A" * 14, "A" * 16   # names "12", "14", "16"


def _obs(seq, name, plate, reads):
    return Obs(key=seq, name=name, flag="", plate=plate, position=1, read_count=reads)


def test_heterozygote_with_dropout_and_false_allele():
    obs = [
        _obs(A, "12", "PP1", 500), _obs(B, "14", "PP1", 480),
        _obs(A, "12", "PP2", 510), _obs(B, "14", "PP2", 470),
        _obs(A, "12", "PP3", 505),            # dropout well (only allele A)
        _obs(C, "16", "PP4", 60),             # false-allele-only well
    ]
    r = compute_consensus(obs, amp_count=4, thr_homo=2, thr_hetero=2)
    assert r.accepted == [A, B]                       # genotype, most-frequent first
    assert [r.names[k] for k in r.accepted] == ["12", "14"]
    assert r.unconfirmed == [C]                        # "16" seen once (< 2)
    assert r.n_amp == 4 and r.n_amp_ok == 4
    assert r.success_rate == 100.0
    assert r.quality_index == 0.5                      # 2 of 4 amps reproduce {12,14}
    assert r.ado == 2                                  # 4 successful - 2 het amps
    assert r.ado_rate == 0.5
    assert r.false_alleles == 1
    assert r.reads_per_amp == 631                      # mean of 980,980,505,60
    assert r.sd_reads_per_amp == 441.7838
    assert r.ncnf_a1 is None and r.ncnf_a2 is None     # no flagged replicates


def test_homozygote():
    obs = [_obs(A, "12", p, 600) for p in ("PP1", "PP2", "PP3")]
    r = compute_consensus(obs, amp_count=3, thr_homo=2, thr_hetero=2)
    assert r.accepted == [A]
    assert r.n_amp == 3 and r.success_rate == 100.0
    assert r.quality_index == 1.0
    assert r.ado == 0                                  # homozygous -> no dropout metric
    assert r.false_alleles == 0
    assert r.sd_reads_per_amp == 0.0


def test_flag_confirmation_and_empty():
    # allele B is flagged in one well but clean in another -> confirmed-but-flagged
    obs = [
        _obs(A, "12", "PP1", 500), Obs(B, "14", "L", "PP1", 1, 300),
        _obs(A, "12", "PP2", 500), _obs(B, "14", "PP2", 400),
    ]
    r = compute_consensus(obs, amp_count=2, thr_homo=2, thr_hetero=2)
    assert set(r.accepted) == {A, B}
    assert r.confirmed.get(B) == 1                     # one flagged replicate of B
    assert r.ncnf_a1 is not None or r.ncnf_a2 == 1 or r.ncnf_a1 == 1

    empty = compute_consensus([], amp_count=2, thr_homo=2, thr_hetero=2)
    assert empty.accepted == [] and empty.n_amp == 2
