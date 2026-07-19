"""Single-animal matching for the individual animal page: compare one animal's REFERENCE sample
against the whole population (MisBase "match one sample"), build the per-locus genotype grid, and
count reliable members. Display-only — reuses the engine (pairwise / decision / runner helpers) and
persists nothing.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Population, Sample, ConsensusGenotype, PopulationMarker, MatchSubgroup
from app.models.enums import MatchCode, MatchTier
from app.services.matching import pairwise, decision, allele_freq
from app.services.matching.runner import _eligible, _genotype, get_or_create_settings

_HIDE = {MatchCode.match, MatchCode.na1, MatchCode.na2}   # not shown as per-locus mismatches


def _context(db: Session, pop: Population):
    """(settings, excluded markers, eligible samples, genotypes, pi_by_marker) for a population."""
    settings = get_or_create_settings(db, pop.project_id, pop.id)
    excluded = set(db.scalars(select(PopulationMarker.marker).where(
        PopulationMarker.population_id == pop.id, PopulationMarker.excluded.is_(True))))
    samples = _eligible(db, pop)
    genos = {s.id: _genotype(db, s.id) for s in samples}
    pi_by_marker = None
    if settings.use_pi_gate:
        stats = allele_freq.compute_population_pi(genos)
        pi_by_marker = {m: (ms.pid, ms.pidsib) for m, ms in stats.items()}
    return settings, excluded, samples, genos, pi_by_marker


def _match_row(sample: Sample, pair, tier) -> dict:
    return {
        "sample_id": sample.id, "system_code": sample.system_code, "name": sample.name,
        "is_reference": False,
        "loci_matched": pair.loci_matched,
        "num_ado_mm": pair.num_ado_mm, "num_1ic": pair.num_1ic, "num_2ic": pair.num_2ic,
        "num_total_ic": pair.num_total_ic,
        "tier": tier.value, "reliable": tier == MatchTier.reliable,
        "mismatches": [{"marker": m, "code": c.value}
                       for m, c in sorted(pair.codes.items()) if c not in _HIDE],
    }


def rematch_reference(db: Session, subgroup: MatchSubgroup) -> dict:
    """Compare the animal's reference against every eligible sample; return the candidate matches
    (tier != none) + the per-locus genotype grid for the reference and those samples."""
    pop = db.get(Population, subgroup.population_id)
    settings, excluded, samples, genos, pi_by_marker = _context(db, pop)
    ref_id = subgroup.reference_sample_id

    smp = {s.id: s for s in samples}
    if ref_id is not None and ref_id not in genos:      # reference may itself be discarded/ineligible
        genos[ref_id] = _genotype(db, ref_id)
        rs = db.get(Sample, ref_id)
        if rs is not None:
            smp[ref_id] = rs
    ref_geno = genos.get(ref_id, {})

    rows: list[dict] = []
    for s in samples:
        if s.id == ref_id:
            continue
        pair = pairwise.compare(ref_geno, genos[s.id], excluded=excluded,
                                pi_by_marker=pi_by_marker, use_pi=settings.use_pi_gate)
        tier = decision.classify(pair, settings)
        if tier == MatchTier.none:
            continue
        rows.append(_match_row(s, pair, tier))
    rows.sort(key=lambda r: (not r["reliable"], r["num_total_ic"], r["num_ado_mm"]))

    ordered = []
    if ref_id is not None and ref_id in smp:
        rs = smp[ref_id]
        ordered.append({
            "sample_id": ref_id, "system_code": rs.system_code, "name": rs.name,
            "is_reference": True, "loci_matched": len(ref_geno),
            "num_ado_mm": 0, "num_1ic": 0, "num_2ic": 0, "num_total_ic": 0,
            "tier": MatchTier.reliable.value, "reliable": True, "mismatches": [],
        })
    ordered += rows

    grid = genotype_grid(db, [r["sample_id"] for r in ordered], ref_id)
    return {"matches": ordered, "genotypes": grid}


def genotype_grid(db: Session, sample_ids: list[int], ref_id: int | None) -> dict:
    """Per-locus genotype grid: markers (rows) × samples (cols). Each cell = allele call + a
    `mismatch` flag vs the reference sample."""
    cons: dict[int, dict] = defaultdict(dict)
    if sample_ids:
        for cg in db.scalars(select(ConsensusGenotype).where(
                ConsensusGenotype.sample_id.in_(sample_ids))):
            cons[cg.sample_id][cg.marker] = cg
    markers = sorted({m for d in cons.values() for m in d})

    def idset(cg) -> frozenset:
        return frozenset({cg.allele1_id, cg.allele2_id} - {None}) if cg else frozenset()

    def call(cg) -> str | None:
        if cg is None:
            return None
        a = [x for x in (cg.allele1, cg.allele2) if x]
        return "/".join(a) if a else None

    ref_geno = {m: idset(cg) for m, cg in cons.get(ref_id, {}).items()}
    samples_out = []
    for sid in sample_ids:
        cells = {}
        for m in markers:
            cg = cons.get(sid, {}).get(m)
            sset = idset(cg)
            rset = ref_geno.get(m, frozenset())
            mism = bool(sid != ref_id and rset and sset
                        and pairwise.compare_marker(rset, sset) != MatchCode.match)
            cells[m] = {"call": call(cg), "mismatch": mism}
        samples_out.append({"sample_id": sid, "is_reference": sid == ref_id, "cells": cells})
    return {"markers": markers, "samples": samples_out}


def reliable_count(db: Session, subgroup: MatchSubgroup) -> int:
    """How many of the animal's current members reliably match its reference (reference included)."""
    pop = db.get(Population, subgroup.population_id)
    settings, excluded, _samples, _genos, pi_by_marker = _context(db, pop)
    ref_id = subgroup.reference_sample_id
    ref_geno = _genotype(db, ref_id) if ref_id is not None else {}
    members = db.scalars(select(Sample).where(Sample.subgroup_id == subgroup.id)).all()
    n = 0
    for s in members:
        if s.id == ref_id:
            n += 1
            continue
        pair = pairwise.compare(ref_geno, _genotype(db, s.id), excluded=excluded,
                                pi_by_marker=pi_by_marker, use_pi=settings.use_pi_gate)
        if decision.classify(pair, settings) == MatchTier.reliable:
            n += 1
    return n
