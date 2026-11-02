"""Delete a kit and everything it produced, in dependency order.

Hand-rolled rather than leaning on ON DELETE CASCADE, for the reason services/project_admin.py
gives: SQLite does not enforce it, so the tests would not exercise the path that runs in
production.

This is the only door in the application through which genotypes can be destroyed, so it comes
with `deletion_impact` — the caller is expected to show those numbers to a person before calling
`delete_kit_everything`.

One consequence that is easy to miss: the matching layer is scoped to a POPULATION, not to a kit.
A kit's samples usually share their population with other kits' samples, so removing them
invalidates the animals that were built from that sample set, and the whole population's matching
data has to be cleared and re-run. `delete_population` already behaves this way when samples move
out of a population. `deletion_impact` reports which populations are affected so it can be said
out loud instead of discovered.
"""
from __future__ import annotations

from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from app.models import (
    Job, Kit, Population, ResultFile, Sample, SampleBatch, ConsensusGenotype,
    ReplicateObservation, kit_access, study_kits,
)
from app.services import storage


def deletion_impact(db: Session, kit: Kit) -> dict:
    """What deleting this kit outright would destroy. Read-only."""
    sample_ids = list(db.scalars(select(Sample.id).where(Sample.kit_id == kit.id)))
    pop_ids = sorted({
        p for p in db.scalars(
            select(Sample.population_id).where(Sample.kit_id == kit.id).distinct()
        ) if p is not None
    })
    n_cons = n_obs = 0
    if sample_ids:
        n_cons = db.scalar(select(func.count()).select_from(ConsensusGenotype)
                           .where(ConsensusGenotype.sample_id.in_(sample_ids)))
        n_obs = db.scalar(select(func.count()).select_from(ReplicateObservation)
                          .where(ReplicateObservation.sample_id.in_(sample_ids)))
    job_ids = list(db.scalars(select(Job.id).where(Job.kit_id == kit.id)))
    n_files = db.scalar(select(func.count()).select_from(ResultFile)
                        .where(ResultFile.job_id.in_(job_ids))) if job_ids else 0
    pops = db.scalars(select(Population).where(Population.id.in_(pop_ids))).all() if pop_ids else []

    return {
        "kit_code": kit.kit_code,
        "samples": len(sample_ids),
        "consensus_genotypes": n_cons,
        "replicate_observations": n_obs,
        "jobs": len(job_ids),
        "result_files": n_files,
        # Clearing these means the animals have to be matched again from what remains.
        "populations_whose_matching_is_cleared": [p.name for p in pops],
        "has_stored_reads": kit.reads is not None,
    }


def delete_kit_everything(db: Session, kit: Kit) -> dict:
    """Delete the kit, its analyses, its samples and everything derived from them.

    Returns what was removed, including the S3 tallies, so the caller can report it.
    """
    kit_id, kit_code = kit.id, kit.kit_code
    sample_ids = list(db.scalars(select(Sample.id).where(Sample.kit_id == kit_id)))
    pop_ids = sorted({
        p for p in db.scalars(
            select(Sample.population_id).where(Sample.kit_id == kit_id).distinct()
        ) if p is not None
    })
    job_ids = list(db.scalars(select(Job.id).where(Job.kit_id == kit_id)))
    prefixes = [
        p for p in db.scalars(select(Job.storage_prefix).where(Job.kit_id == kit_id)) if p
    ]
    sheet_keys = [
        k for k in db.scalars(
            select(SampleBatch.sample_sheet_key).where(SampleBatch.job_id.in_(job_ids))
        ) if k
    ] if job_ids else []
    read_keys = [kit.reads.fastq1_key, kit.reads.fastq2_key] if kit.reads else []

    # 1. the samples and everything hanging off them. The matching purge has to come first or the
    #    matches rows block the sample delete; both helpers live in population_admin, and are
    #    reused rather than re-copied — a third copy of this ordering would be a third thing to
    #    keep in step.
    from app.services.population_admin import purge_population_scoped_data, _delete_samples
    purge_population_scoped_data(db, pop_ids)
    _delete_samples(db, sample_ids)

    # 2. the analyses. Their batches and result rows are delete-orphan, but spell them out: the
    #    bulk delete below never loads the ORM objects that would trigger that cascade.
    if job_ids:
        db.execute(delete(ResultFile).where(ResultFile.job_id.in_(job_ids)))
        db.execute(delete(SampleBatch).where(SampleBatch.job_id.in_(job_ids)))
        db.execute(delete(Job).where(Job.id.in_(job_ids)))

    # 3. the kit itself. tag_columns/controls/reads/analysis_setup are delete-orphan on the ORM
    #    object, and the two association rows have DB cascades; deleting via the loaded object
    #    gets all of it on both Postgres and SQLite.
    db.execute(kit_access.delete().where(kit_access.c.kit_id == kit_id))
    db.execute(study_kits.delete().where(study_kits.c.kit_id == kit_id))
    db.delete(kit)
    db.commit()

    # 4. storage, after the rows are safely gone. The other order risks deleting results that a
    #    surviving job row still advertises.
    objects = freed = 0
    for prefix in set(prefixes) | {f"results/{kit_code}/", f"reads/kit/{kit_id}/"}:
        n, b = storage.delete_prefix(prefix.rstrip("/") + "/")
        objects += n
        freed += b
    for key in sheet_keys + read_keys:
        storage.delete_object(key)

    return {
        "kit_code": kit_code,
        "samples": len(sample_ids),
        "jobs": len(job_ids),
        "objects_deleted": objects,
        "bytes_freed": freed,
    }
