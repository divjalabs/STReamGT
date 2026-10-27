"""Pure, pandas-free consensus math — the backend twin of pipeline/bin/callConsensus.py.

Keyed on the allele's SEQUENCE (its identity), not the display name. Given the called
observations for one Sample x Marker plus the number of attempted amplifications, it reproduces
the pipeline's consensus row and metrics exactly (see tests/test_consensus_core.py for parity).
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Obs:
    """One called-allele observation in one PCR well."""
    key: str                 # allele identity = sequence
    name: str                # display name (Length[_Variant])
    flag: str = ""           # "" == clean
    plate: str | None = None
    position: int | None = None
    read_count: int | None = None


@dataclass
class ConsensusResult:
    accepted: list[str] = field(default_factory=list)   # sequences, ordered (genotype), up to 4
    names: dict = field(default_factory=dict)           # sequence -> display name
    confirmed: dict = field(default_factory=dict)       # sequence -> n_flagged replicates
    unconfirmed: list[str] = field(default_factory=list)  # sequences
    ncnf_a1: int | None = None
    ncnf_a2: int | None = None
    false_alleles: int = 0
    n_amp: int = 0
    n_amp_ok: int = 0
    success_rate: float = 0.0
    ado: int = 0
    ado_rate: float = 0.0
    quality_index: float = 0.0
    reads_per_amp: int = 0
    sd_reads_per_amp: float = 0.0

    def confirmed_names(self) -> list[str]:
        return [self.names.get(k, k) for k in self.confirmed]

    def unconfirmed_names(self) -> list[str]:
        return [self.names.get(k, k) for k in self.unconfirmed]


def _amp_metrics(observations, clean, genotype_set, is_heterozygous, amp_count):
    """Amplification-based success / dropout / quality (mirrors amplification_metrics)."""
    amps: dict = {}
    for o in observations:
        amps.setdefault((o.plate, o.position), []).append(o)

    n_success = n_het = n_perfect = 0
    amp_reads: list[float] = []
    for _key, rows in amps.items():
        usable_rows = [r for r in rows if r.key in clean]
        usable = {r.key for r in usable_rows}
        if not usable:                              # amp produced nothing confirmable
            continue
        n_success += 1
        amp_reads.append(float(sum((r.read_count or 0) for r in usable_rows)))
        if len(usable) == 2:
            n_het += 1
        if usable == genotype_set:                  # amp reproduced the whole consensus genotype
            n_perfect += 1

    n_amps = max(int(amp_count), len(amps))         # amplifications table is authoritative
    success_rate = 100 * n_success / n_amps if n_amps else 0.0
    quality_index = n_perfect / n_amps if n_amps else 0.0
    ado = (n_success - n_het) if is_heterozygous else 0
    ado = max(ado, 0)
    ado_rate = ado / n_success if n_success else 0.0
    reads_per_amp = int(round(statistics.fmean(amp_reads))) if amp_reads else 0
    sd_reads = round(statistics.stdev(amp_reads), 4) if len(amp_reads) > 1 else 0.0  # sample SD
    return n_amps, n_success, success_rate, quality_index, ado, ado_rate, reads_per_amp, sd_reads


def compute_consensus(observations: list[Obs], amp_count: int,
                      thr_homo: int, thr_hetero: int) -> ConsensusResult:
    """One consensus genotype for a Sample x Marker from its called observations.

    observations : called alleles only (one per well per allele).
    amp_count    : attempted amplifications (distinct Plate x Position), incl. failed wells.
    """
    res = ConsensusResult()
    res.names = {o.key: o.name for o in observations}
    if not observations:
        res.n_amp = int(amp_count)
        return res

    # counts = observations per allele (sequence), most-frequent-first, name as tie-break.
    counts = Counter(o.key for o in observations)
    counts = dict(sorted(counts.items(), key=lambda kv: (-kv[1], res.names.get(kv[0], kv[0]))))
    threshold = thr_hetero if len(counts) > 1 else thr_homo

    clean: set = set()
    for key in counts:
        rows = [o for o in observations if o.key == key]
        n_unflagged = sum(1 for o in rows if o.flag == "")
        n_flagged = sum(1 for o in rows if o.flag != "")
        if n_unflagged == 0:                        # every replicate flagged -> unconfirmed
            res.unconfirmed.append(key)
            continue
        clean.add(key)                              # a clean copy confirms flagged copies anywhere
        if n_flagged > 0:
            res.confirmed[key] = n_flagged
        (res.accepted if len(rows) >= threshold else res.unconfirmed).append(key)

    genotype_set = set(res.accepted[:2])
    (res.n_amp, res.n_amp_ok, res.success_rate, res.quality_index,
     res.ado, res.ado_rate, res.reads_per_amp, res.sd_reads_per_amp) = _amp_metrics(
        observations, clean, genotype_set, is_heterozygous=len(res.accepted) >= 2,
        amp_count=amp_count)

    # FalseAlleles: observation counts of the 3rd-5th most frequent alleles (past the top-2).
    res.false_alleles = sum(list(counts.values())[2:5])

    padded = (res.accepted + [None, None])[:2]
    res.ncnf_a1 = res.confirmed.get(padded[0]) if padded[0] else None
    res.ncnf_a2 = res.confirmed.get(padded[1]) if padded[1] else None
    return res
