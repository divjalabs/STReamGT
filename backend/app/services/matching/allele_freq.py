"""Per-population, per-marker allele frequencies and probability of identity (Waits et al. 2001).

Frequencies are computed from consensus genotypes (allele-id sets), NOT from the pipeline's
per-sequence read-count frequency file. A homozygote (size-1 set) contributes 2 copies of its
allele; a heterozygote (size-2 set) contributes 1 each.

PID  = 2*(Σpi²)² − Σpi⁴                                  (random individuals share genotype)
PIDsib = 0.25 + 0.5·Σpi² + 0.5·(Σpi²)² − 0.25·Σpi⁴       (full sibs)
Ae   = 1/Σpi²
These are the theoretical (HWE) forms; a small-sample unbiased correction is a future refinement.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarkerStats:
    n_samples: int
    n_alleles: int
    effective_alleles: float
    pid: float
    pidsib: float
    frequencies: dict           # allele_id -> frequency
    observations: dict          # allele_id -> allele-copy count


def marker_frequencies(genotypes_at_marker) -> MarkerStats:
    """genotypes_at_marker: iterable of allele-id sets (one per sample that typed this marker)."""
    obs: dict = {}
    n_samples = 0
    for gset in genotypes_at_marker:
        if not gset:
            continue
        n_samples += 1
        alleles = list(gset)
        if len(alleles) == 1:                        # homozygote -> 2 copies
            obs[alleles[0]] = obs.get(alleles[0], 0) + 2
        else:                                        # heterozygote -> 1 copy each
            for a in alleles:
                obs[a] = obs.get(a, 0) + 1
    total = 2 * n_samples
    freqs = {a: c / total for a, c in obs.items()} if total else {}
    a2 = sum(p * p for p in freqs.values())
    a4 = sum(p ** 4 for p in freqs.values())
    ae = (1.0 / a2) if a2 else 0.0
    pid = 2 * a2 * a2 - a4
    pidsib = 0.25 + 0.5 * a2 + 0.5 * a2 * a2 - 0.25 * a4
    return MarkerStats(n_samples=n_samples, n_alleles=len(freqs), effective_alleles=ae,
                       pid=pid, pidsib=pidsib, frequencies=freqs, observations=obs)


def compute_population_pi(genotypes: dict) -> dict:
    """genotypes: sample_id -> {marker -> allele-id set}. Returns marker -> MarkerStats."""
    by_marker: dict = {}
    for geno in genotypes.values():
        for marker, gset in geno.items():
            by_marker.setdefault(marker, []).append(gset)
    return {marker: marker_frequencies(sets) for marker, sets in by_marker.items()}
