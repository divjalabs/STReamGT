"""Delete a project and all of its data, in dependency order (DB-agnostic: doesn't rely on
ON DELETE CASCADE, which SQLite doesn't enforce). Jobs are preserved but detached from the project.
"""
from __future__ import annotations

from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session

from app.models import (
    Job, Project, Population, Study, SampleType, Sample, ConsensusGenotype, ConsensusEditLog,
    ReferenceAllele, ReplicateObservation, ReplicateAmplification,
    MatchingSettings, MatchingRun, Match, MatchSubgroup, MatchSupergroup, match_supergroup_members,
    MatchingLog, PopulationMarker, PopulationAlleleFrequency, project_access, study_kits,
)


def delete_project(db: Session, project_id: int) -> None:
    pop_ids = list(db.scalars(select(Population.id).where(Population.project_id == project_id)))
    sample_ids = list(db.scalars(select(Sample.id).where(Sample.project_id == project_id)))

    # jobs are independent artifacts — keep them, just detach from the vanishing project
    db.execute(update(Job).where(Job.project_id == project_id)
               .values(project_id=None, default_population_id=None, default_study_id=None))

    if sample_ids:
        db.execute(update(Sample).where(Sample.id.in_(sample_ids)).values(subgroup_id=None))

    from app.services.population_admin import purge_population_scoped_data
    purge_population_scoped_data(db, pop_ids)

    if sample_ids:
        cons_ids = list(db.scalars(select(ConsensusGenotype.id)
                                   .where(ConsensusGenotype.sample_id.in_(sample_ids))))
        if cons_ids:
            db.execute(delete(ConsensusEditLog).where(ConsensusEditLog.consensus_id.in_(cons_ids)))
        db.execute(delete(ConsensusGenotype).where(ConsensusGenotype.sample_id.in_(sample_ids)))
        db.execute(delete(ReplicateObservation).where(ReplicateObservation.sample_id.in_(sample_ids)))
        db.execute(delete(ReplicateAmplification).where(ReplicateAmplification.sample_id.in_(sample_ids)))
        db.execute(delete(Sample).where(Sample.id.in_(sample_ids)))

    db.execute(delete(ReferenceAllele).where(ReferenceAllele.project_id == project_id))
    db.execute(delete(MatchingSettings).where(MatchingSettings.project_id == project_id))
    db.execute(delete(SampleType).where(SampleType.project_id == project_id))
    study_ids = list(db.scalars(select(Study.id).where(Study.project_id == project_id)))
    if study_ids:
        db.execute(study_kits.delete().where(study_kits.c.study_id.in_(study_ids)))
    db.execute(delete(Study).where(Study.project_id == project_id))
    db.execute(delete(Population).where(Population.project_id == project_id))
    db.execute(project_access.delete().where(project_access.c.project_id == project_id))
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()
