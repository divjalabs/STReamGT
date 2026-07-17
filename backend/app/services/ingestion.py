"""Ingest a finished job's pipeline outputs into the structured animal/sample store.

Called at job-success time (worker/tasks.py::execute_job) when the job has a project_id. Parses
the consensus / reference-allele / genotypes / positions tables and upserts them into
samples / replicate_* / consensus_genotypes / reference_alleles. Idempotent per job: re-ingest
replaces this job's replicate rows and non-locked consensus rows without duplicating samples.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models import (
    Job, Sample, ReplicateObservation, ReplicateAmplification, ConsensusGenotype,
    ReferenceAllele, ConsensusSource,
)
from app.services import consensus_parsers as P


def _read(path: str | None) -> str:
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            return fh.read()
    return ""


def ingest_job_outputs(
    db: Session,
    job: Job,
    *,
    consensus_path: str | None = None,
    reference_alleles_path: str | None = None,
    genotypes_path: str | None = None,
    positions_path: str | None = None,
) -> dict:
    """Read the pipeline output files and ingest them for `job`. Returns a small summary dict."""
    return ingest_parsed(
        db, job,
        consensus=P.parse_consensus(_read(consensus_path)),
        ref_alleles=P.parse_reference_alleles(_read(reference_alleles_path)),
        genotypes=P.parse_genotypes(_read(genotypes_path)),
        positions=P.parse_positions(_read(positions_path)),
    )


def ingest_parsed(
    db: Session,
    job: Job,
    *,
    consensus: list[P.ConsensusRow],
    ref_alleles: list[P.RefAlleleRow],
    genotypes: list[P.GenotypeRow],
    positions: list[P.PositionRow],
) -> dict:
    if not job.project_id:
        return {"skipped": "job has no project_id"}

    project_id = job.project_id

    # 1) Reference alleles: upsert keyed (project, marker, sequence); keep existing name/variant.
    #    reference_alleles IS the allele identity (marker+sequence). We build lookups so consensus
    #    and replicates link to that identity rather than to the (drift-prone) name string.
    name_by_seq: dict[tuple[str, str], str] = {}
    ref_row_by_seq: dict[tuple[str, str], ReferenceAllele] = {}
    for ra in ref_alleles:
        key = (ra.marker, ra.sequence)
        existing = db.scalar(
            select(ReferenceAllele).where(
                ReferenceAllele.project_id == project_id,
                ReferenceAllele.marker == ra.marker,
                ReferenceAllele.sequence == ra.sequence,
            )
        )
        if existing:
            existing.n = ra.n  # refresh count; preserve variant/allele_name (name stability)
            row = existing
        else:
            row = ReferenceAllele(
                project_id=project_id, marker=ra.marker, sequence=ra.sequence,
                length=ra.length, variant=ra.variant, allele_name=ra.allele_name, n=ra.n,
            )
            db.add(row)
        name_by_seq[key] = row.allele_name
        ref_row_by_seq[key] = row
    db.flush()  # assign ids to new reference_alleles rows
    # Consensus output names alleles; map name -> sequence-backed allele id (unique within a run).
    id_by_name = {(marker, r.allele_name): r.id for (marker, _seq), r in ref_row_by_seq.items()}

    # 2) Samples: find-or-create by (job_id, name). Collect the ids we touch this run.
    sample_ids: dict[str, int] = {}
    names = {r.sample_name for r in consensus} | {g.sample_name for g in genotypes} \
        | {p.sample_name for p in positions}
    for name in names:
        sample = db.scalar(
            select(Sample).where(Sample.job_id == job.id, Sample.name == name)
        )
        if sample is None:
            sample = Sample(
                public_id=uuid.uuid4().hex,
                system_code="",  # set after flush (needs id)
                project_id=project_id,
                population_id=job.default_population_id,
                study_id=job.default_study_id,
                kit_id=job.kit_id,
                job_id=job.id,
                name=name,
            )
            db.add(sample)
            db.flush()
            sample.system_code = f"S-{sample.id:06d}"
        sample_ids[name] = sample.id
    db.flush()

    # 3) Replicates: replace this job's rows for the touched samples.
    ids = list(sample_ids.values())
    if ids:
        db.execute(delete(ReplicateObservation).where(ReplicateObservation.sample_id.in_(ids)))
        db.execute(delete(ReplicateAmplification).where(ReplicateAmplification.sample_id.in_(ids)))
    for g in genotypes:
        sid = sample_ids.get(g.sample_name)
        if sid is None:
            continue
        db.add(ReplicateObservation(
            sample_id=sid, marker=g.marker, plate=g.plate, position=g.position,
            tag_combo=g.tag_combo, run_name=g.run_name, read_count=g.read_count,
            length=g.length, called=g.called, flag=g.flag, stutter=g.stutter,
            sequence=g.sequence,
            allele_name=name_by_seq.get((g.marker, g.sequence)) if g.sequence else None,
        ))
    for p in positions:
        sid = sample_ids.get(p.sample_name)
        if sid is None:
            continue
        db.add(ReplicateAmplification(
            sample_id=sid, marker=p.marker, plate=p.plate, position=p.position,
            tag_combo=p.tag_combo, run_name=p.run_name,
        ))

    # 4) Consensus: upsert per (sample_id, marker), skipping locked rows.
    n_consensus = 0
    for c in consensus:
        sid = sample_ids.get(c.sample_name)
        if sid is None:
            continue
        row = db.scalar(
            select(ConsensusGenotype).where(
                ConsensusGenotype.sample_id == sid, ConsensusGenotype.marker == c.marker
            )
        )
        if row and row.is_locked:
            continue  # preserve manual locks/edits
        if row is None:
            row = ConsensusGenotype(sample_id=sid, marker=c.marker)
            db.add(row)
        row.allele1, row.allele2 = c.allele1, c.allele2
        row.allele3, row.allele4 = c.allele3, c.allele4
        # Link each consensus allele to its sequence-backed identity (reference_alleles.id).
        row.allele1_id = id_by_name.get((c.marker, c.allele1)) if c.allele1 else None
        row.allele2_id = id_by_name.get((c.marker, c.allele2)) if c.allele2 else None
        row.allele3_id = id_by_name.get((c.marker, c.allele3)) if c.allele3 else None
        row.allele4_id = id_by_name.get((c.marker, c.allele4)) if c.allele4 else None
        row.ncnf_a1, row.ncnf_a2 = c.ncnf_a1, c.ncnf_a2
        row.confirmed_alleles = c.confirmed_alleles
        row.unconfirmed_alleles = c.unconfirmed_alleles
        row.n_amp, row.n_amp_ok = c.n_amp, c.n_amp_ok
        row.success_rate = c.success_rate
        row.ado, row.ado_rate = c.ado, c.ado_rate
        row.quality_index = c.quality_index
        row.false_alleles = c.false_alleles
        row.reads_per_amp = c.reads_per_amp
        row.sd_reads_per_amp = c.sd_reads_per_amp
        row.source = ConsensusSource.pipeline
        row.is_edited = False
        n_consensus += 1

    db.flush()
    from app.services.qc import run_sample_qc          # QC gates + sex, post-ingestion
    run_sample_qc(db, list(sample_ids.values()))
    return {
        "samples": len(sample_ids),
        "consensus": n_consensus,
        "reference_alleles": len(ref_alleles),
        "replicate_observations": len(genotypes),
        "replicate_amplifications": len(positions),
    }
