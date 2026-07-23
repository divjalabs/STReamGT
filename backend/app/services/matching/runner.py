"""Orchestrate a matching run for one population: eligibility -> genotypes -> all-pairs
pairwise -> reliable matches -> reference-anchored subgroups (= animals), persisted.

A full run rebuilds the population's matches/subgroups. Pairwise is all-pairs here (correct and
instant at per-population scale); the coarse-cluster / blocking optimisation (see the plan) slots
in when populations get large.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session

from app.models import (
    Population, Sample, Study, SampleType, ConsensusGenotype,
    MatchingSettings, MatchingRun, Match, MatchSubgroup, MatchSupergroup,
    match_supergroup_members, MatchingLog,
    PopulationMarker, PopulationAlleleFrequency,
    RunStatus, MatchTier, MismatchMetric,
)
from app.services.matching import pairwise, decision, allele_freq, grouping, clique_qc


def get_or_create_settings(db: Session, project_id: int, population_id: int) -> MatchingSettings:
    row = db.scalar(select(MatchingSettings).where(
        MatchingSettings.project_id == project_id,
        MatchingSettings.population_id == population_id))
    if row is None:
        row = db.scalar(select(MatchingSettings).where(
            MatchingSettings.project_id == project_id,
            MatchingSettings.population_id.is_(None)))
    if row is None:
        row = MatchingSettings(project_id=project_id, population_id=None, name="default")
        db.add(row)
        db.flush()
    return row


def _eligible(db: Session, population: Population) -> list[Sample]:
    project_id = population.project_id
    samples = db.scalars(select(Sample).where(Sample.population_id == population.id)).all()
    studies = {s.id: s for s in db.scalars(
        select(Study).where(Study.project_id == project_id))}
    types = {t.id: t for t in db.scalars(select(SampleType).where(
        (SampleType.project_id == project_id) | (SampleType.project_id.is_(None))))}
    out = []
    for s in samples:
        if s.is_control:            # controls never participate in matching / allele frequencies
            continue
        if s.discard_sample or s.animal_matchlock:
            continue
        st = studies.get(s.study_id)
        if st is not None and not st.include_in_matching:
            continue
        tp = types.get(s.sample_type_id)
        if tp is not None and tp.exclude_from_analysis:
            continue
        out.append(s)
    return out


def _genotype(db: Session, sample_id: int) -> dict:
    """marker -> frozenset of allele identities (reference_alleles ids == sequences)."""
    geno: dict = {}
    for cg in db.scalars(select(ConsensusGenotype).where(
            ConsensusGenotype.sample_id == sample_id)):
        ids = {cg.allele1_id, cg.allele2_id} - {None}
        if ids:
            geno[cg.marker] = frozenset(ids)
    return geno


def _persist_pi(db: Session, population_id: int, stats: dict, excluded: set) -> None:
    db.execute(delete(PopulationAlleleFrequency).where(
        PopulationAlleleFrequency.population_id == population_id))
    db.execute(delete(PopulationMarker).where(PopulationMarker.population_id == population_id))
    now = datetime.now(timezone.utc)
    for marker, ms in stats.items():
        db.add(PopulationMarker(
            population_id=population_id, marker=marker, n_samples=ms.n_samples,
            n_alleles=ms.n_alleles, effective_alleles=ms.effective_alleles,
            pi=ms.pid, pi_sib=ms.pidsib, excluded=marker in excluded, computed_at=now))
        for allele_id, freq in ms.frequencies.items():
            db.add(PopulationAlleleFrequency(
                population_id=population_id, marker=marker, allele_name=str(allele_id),
                observations=ms.observations[allele_id], frequency=freq, computed_at=now))


def run_matching(db: Session, population_id: int, *, user_id: int | None = None) -> MatchingRun:
    pop = db.get(Population, population_id)
    if pop is None:
        raise ValueError("population not found")
    settings = get_or_create_settings(db, pop.project_id, population_id)

    run = MatchingRun(public_id=uuid.uuid4().hex, population_id=population_id,
                      triggered_by=user_id, status=RunStatus.running,
                      started_at=datetime.now(timezone.utc))
    db.add(run)
    db.flush()

    # preserved user-set locus exclusions
    excluded = set(db.scalars(select(PopulationMarker.marker).where(
        PopulationMarker.population_id == population_id, PopulationMarker.excluded.is_(True))))

    try:
        samples = _eligible(db, pop)
        genos = {s.id: _genotype(db, s.id) for s in samples}

        pi_by_marker = None
        if settings.use_pi_gate:
            stats = allele_freq.compute_population_pi(genos)
            pi_by_marker = {m: (ms.pid, ms.pidsib) for m, ms in stats.items()}
            _persist_pi(db, population_id, stats, excluded)

        # fresh rebuild: detach samples, clear prior matches/subgroups/supergroups
        db.execute(update(Sample).where(Sample.population_id == population_id)
                   .values(subgroup_id=None))
        db.execute(delete(Match).where(Match.population_id == population_id))
        db.execute(delete(MatchSupergroup).where(MatchSupergroup.population_id == population_id))
        db.execute(delete(MatchSubgroup).where(MatchSubgroup.population_id == population_id))
        db.flush()

        meta_by_id = {s.id: grouping.SampleMeta(
            sample_id=s.id, is_animal_reference=s.is_animal_reference,
            genotype_ok=s.genotype_ok, quality_index=s.quality_index) for s in samples}

        # Exact-collapse: samples with an identical genotype (over non-excluded markers) are the
        # same individual (0 mismatches -> reliable). Collapse each distinct genotype to one
        # representative (its highest-priority sample), run the expensive pairwise over
        # representatives only, then expand membership. Grouping is identical to all-pairs.
        members_of: dict = defaultdict(list)          # genotype signature -> [sample ids]
        for s in samples:
            g = genos[s.id]
            sig = frozenset((m, g[m]) for m in (set(g) - excluded))
            members_of[sig].append(s.id)
        reps: list = []
        group_of_rep: dict = {}                       # representative id -> all sample ids collapsed
        for mem in members_of.values():
            rep = max(mem, key=lambda sid: grouping._priority(meta_by_id[sid]))
            reps.append(rep)
            group_of_rep[rep] = mem

        # Coarse candidate screen: a cheap necessary condition for a match, so the expensive
        # per-marker MatchCode + PI comparison runs ONLY on close representative pairs. Same result
        # as all-pairs (a pruned pair is provably `none`).
        if settings.mismatch_metric == MismatchMetric.flat:
            soft_budget = settings.tm_possible
        else:
            soft_budget = settings.max_ado_mm_match + settings.max_total_mm_match
        typed = {r: (set(genos[r]) - excluded) for r in reps}

        reliable_pairs: set = set()
        n_matches = 0
        n_screened = 0
        for i in range(len(reps)):
            a = reps[i]
            ga, ta = genos[a], typed[a]
            for j in range(i + 1, len(reps)):
                b = reps[j]
                shared = ta & typed[b]
                if len(shared) < settings.min_shared_loci:
                    continue
                gb = genos[b]
                if sum(1 for m in shared if ga[m].isdisjoint(gb[m])) > soft_budget:
                    continue                          # too many hard differences to ever match
                n_screened += 1
                pair = pairwise.compare(ga, gb, excluded=excluded,
                                        pi_by_marker=pi_by_marker, use_pi=settings.use_pi_gate)
                tier = decision.classify(pair, settings)
                if tier == MatchTier.none:
                    continue
                db.add(Match(
                    run_id=run.id, population_id=population_id, sample_a_id=a, sample_b_id=b,
                    loci_matched=pair.loci_matched, loci_compared=pair.loci_compared,
                    num_ado_mm=pair.num_ado_mm, num_1ic=pair.num_1ic, num_2ic=pair.num_2ic,
                    num_total_ic=pair.num_total_ic, flat_mismatch=pair.flat_mismatch,
                    d_pi=pair.d_pi, d_pi_sib=pair.d_pi_sib, tier=tier))
                n_matches += 1
                if tier == MatchTier.reliable:
                    reliable_pairs.add(frozenset((a, b)))

        subgroups = grouping.reference_anchored([meta_by_id[r] for r in reps], reliable_pairs)

        code_by_id = {s.id: s.system_code for s in samples}
        sg_rows: list = []
        sample_to_idx: dict = {}                       # representative id -> subgroup index
        for idx, sg in enumerate(subgroups):
            all_members = [sid for rep in sg.members for sid in group_of_rep[rep]]  # expand collapse
            row = MatchSubgroup(
                public_id=uuid.uuid4().hex, population_id=population_id, run_id=run.id,
                label=code_by_id.get(sg.reference), reference_sample_id=sg.reference,
                n_samples=len(all_members))
            db.add(row)
            db.flush()
            db.execute(update(Sample).where(Sample.id.in_(all_members)).values(subgroup_id=row.id))
            sg_rows.append(row)
            for rep in sg.members:
                sample_to_idx[rep] = idx

        # Supergroups (QC): a reliable match between samples in DIFFERENT subgroups links those
        # animals. Union-find over subgroups; a supergroup with >=2 animals is a QC flag (possible
        # same individual / genotyping error) — NOT an auto-merge.
        parent = list(range(len(subgroups)))

        def _find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for pair in reliable_pairs:
            a, b = tuple(pair)
            ia, ib = sample_to_idx.get(a), sample_to_idx.get(b)
            if ia is not None and ib is not None and ia != ib:
                parent[_find(ia)] = _find(ib)
        comps: dict = defaultdict(list)
        for idx in range(len(subgroups)):
            comps[_find(idx)].append(idx)
        n_super = 0
        for members in comps.values():
            if len(members) < 2:
                continue
            sup = MatchSupergroup(
                population_id=population_id, run_id=run.id,
                label="+".join(sg_rows[i].label or str(sg_rows[i].id) for i in members))
            db.add(sup)
            db.flush()
            for i in members:
                db.execute(match_supergroup_members.insert().values(
                    supergroup_id=sup.id, subgroup_id=sg_rows[i].id))
            n_super += 1

        n_pairs = len(reps) * (len(reps) - 1) // 2
        db.add(MatchingLog(run_id=run.id, seq=1, level="info",
                           message=f"{len(samples)} samples ({len(reps)} distinct genotypes), "
                                   f"{n_matches} matches, {len(subgroups)} animals, "
                                   f"{n_super} supergroup(s); {n_screened}/{n_pairs} "
                                   f"representative pairs fully compared"))

        # QC: batch maximal-clique grouping (Pirog) vs the reference-anchored subgroups (over reps).
        ref_part = {rep: idx for idx, sg in enumerate(subgroups) for rep in sg.members}
        clique_part = clique_qc.clique_partition(reps, reliable_pairs)
        disagree = clique_qc.disagreements(ref_part, clique_part)
        if disagree:
            db.add(MatchingLog(run_id=run.id, seq=2, level="warning",
                               message=f"clique QC: {len(disagree)} grouping disagreement(s) "
                                       "— reference-anchored vs maximal-clique"))
        run.status = RunStatus.succeeded
        run.n_samples = len(samples)
        run.n_matches = n_matches
        run.n_subgroups = len(subgroups)
        run.finished_at = datetime.now(timezone.utc)
        db.flush()
    except Exception as exc:  # noqa: BLE001
        run.status = RunStatus.failed
        run.error_message = str(exc)[:4000]
        run.finished_at = datetime.now(timezone.utc)
        db.flush()
        raise
    return run
