"""One-off cleanup of samples duplicated by past kit reanalyses.

A reanalysis used to create a new Job and re-ingest into new Sample rows with the same names, so a
project could hold several copies of the same specimen. Ingestion now keys on (project, kit, name);
this removes the pre-existing duplicates, keeping the most-recent run's copy.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Sample
from app.services.population_admin import purge_population_scoped_data, _delete_samples


def dedup_duplicate_samples(db: Session) -> dict:
    """Per (project, kit, name), keep the sample from the most-recent job and delete older duplicates
    (+ their consensus/replicates). Matching for affected populations is purged (stale after a
    reanalysis anyway → re-run it). Returns a summary."""
    groups: dict[tuple, list[Sample]] = defaultdict(list)
    for s in db.scalars(select(Sample).where(Sample.kit_id.is_not(None))):
        groups[(s.project_id, s.kit_id, s.name)].append(s)

    loser_ids: list[int] = []
    affected_pops: set[int] = set()
    dup_groups = 0
    for samples in groups.values():
        if len(samples) < 2:
            continue
        dup_groups += 1
        samples.sort(key=lambda s: (s.job_id or 0, s.id))   # survivor = most-recent run
        for s in samples[:-1]:
            loser_ids.append(s.id)
        for s in samples:
            if s.population_id:
                affected_pops.add(s.population_id)

    if loser_ids:
        purge_population_scoped_data(db, list(affected_pops))
        _delete_samples(db, loser_ids)
        db.flush()
    return {"groups": dup_groups, "deleted": len(loser_ids), "pops_purged": len(affected_pops)}
