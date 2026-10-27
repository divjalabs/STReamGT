"""Delete/reorganise populations and studies, cleaning up dependent data in dependency order
(DB-agnostic: doesn't rely on ON DELETE CASCADE, which SQLite doesn't enforce).

- delete_study: non-destructive to samples — they fall back to the study's parent population.
- delete_population: transfer its samples+studies to another population, or delete them; either way
  its population-scoped matching results are purged.
"""
from __future__ import annotations

from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session

from app.models import (
    Study, Population, Sample, ConsensusGenotype, ConsensusEditLog,
    ReplicateObservation, ReplicateAmplification,
    MatchingRun, Match, MatchSubgroup, MatchSupergroup, match_supergroup_members,
    MatchingLog, PopulationMarker, PopulationAlleleFrequency, study_kits, AnimalOverride,
)


def purge_population_scoped_data(db: Session, pop_ids: list[int]) -> None:
    """Delete everything keyed on a population *except* its samples and the population row itself:
    matching runs/matches/subgroups/supergroups + per-population marker/frequency rows. Also detaches
    any samples still assigned to those populations' animals (subgroups) so the subgroups can go."""
    if not pop_ids:
        return
    db.execute(update(Sample).where(Sample.population_id.in_(pop_ids)).values(subgroup_id=None))
    run_ids = list(db.scalars(select(MatchingRun.id).where(MatchingRun.population_id.in_(pop_ids))))
    sup_ids = list(db.scalars(select(MatchSupergroup.id).where(MatchSupergroup.population_id.in_(pop_ids))))
    db.execute(delete(Match).where(Match.population_id.in_(pop_ids)))
    if run_ids:
        db.execute(delete(MatchingLog).where(MatchingLog.run_id.in_(run_ids)))
    if sup_ids:
        db.execute(match_supergroup_members.delete()
                   .where(match_supergroup_members.c.supergroup_id.in_(sup_ids)))
    db.execute(delete(MatchSupergroup).where(MatchSupergroup.population_id.in_(pop_ids)))
    db.execute(delete(MatchSubgroup).where(MatchSubgroup.population_id.in_(pop_ids)))
    db.execute(delete(MatchingRun).where(MatchingRun.population_id.in_(pop_ids)))
    db.execute(delete(PopulationMarker).where(PopulationMarker.population_id.in_(pop_ids)))
    db.execute(delete(PopulationAlleleFrequency)
               .where(PopulationAlleleFrequency.population_id.in_(pop_ids)))
    # persistent per-animal overrides (only removed when the population itself is deleted)
    db.execute(delete(AnimalOverride).where(AnimalOverride.population_id.in_(pop_ids)))


def _delete_samples(db: Session, sample_ids: list[int]) -> None:
    if not sample_ids:
        return
    cons_ids = list(db.scalars(select(ConsensusGenotype.id)
                               .where(ConsensusGenotype.sample_id.in_(sample_ids))))
    if cons_ids:
        db.execute(delete(ConsensusEditLog).where(ConsensusEditLog.consensus_id.in_(cons_ids)))
    db.execute(delete(ConsensusGenotype).where(ConsensusGenotype.sample_id.in_(sample_ids)))
    db.execute(delete(ReplicateObservation).where(ReplicateObservation.sample_id.in_(sample_ids)))
    db.execute(delete(ReplicateAmplification).where(ReplicateAmplification.sample_id.in_(sample_ids)))
    db.execute(delete(Sample).where(Sample.id.in_(sample_ids)))


def _delete_studies(db: Session, study_ids: list[int]) -> None:
    if not study_ids:
        return
    db.execute(study_kits.delete().where(study_kits.c.study_id.in_(study_ids)))
    db.execute(delete(Study).where(Study.id.in_(study_ids)))


def delete_study(db: Session, study: Study) -> None:
    """Delete a study; its samples stay, falling back to the study's parent population."""
    if study.population_id is not None:
        db.execute(update(Sample).where(Sample.study_id == study.id)
                   .values(population_id=study.population_id))
    db.execute(update(Sample).where(Sample.study_id == study.id).values(study_id=None))
    _delete_studies(db, [study.id])
    db.commit()


def delete_population(
    db: Session, population: Population, *,
    reassign_to_id: int | None = None, delete_samples: bool = False,
) -> None:
    """Delete a population. With reassign_to_id, its samples+studies move to that population;
    with delete_samples, they are deleted. Its matching results are always purged."""
    pid = population.id
    if reassign_to_id is not None:
        # matching is population-scoped, so moved samples lose their animal assignment
        db.execute(update(Sample).where(Sample.population_id == pid)
                   .values(population_id=reassign_to_id, subgroup_id=None))
        db.execute(update(Study).where(Study.population_id == pid)
                   .values(population_id=reassign_to_id))

    purge_population_scoped_data(db, [pid])

    if delete_samples:
        study_ids = list(db.scalars(select(Study.id).where(Study.population_id == pid)))
        _delete_studies(db, study_ids)
        sample_ids = list(db.scalars(select(Sample.id).where(Sample.population_id == pid)))
        _delete_samples(db, sample_ids)

    db.execute(delete(Population).where(Population.id == pid))
    db.commit()
