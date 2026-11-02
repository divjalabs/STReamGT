"""Save/replace a kit's analysis setup — the sheet filled in before the FASTQ arrives (one per kit).

Mirrors services/kit_reads.set_kit_reads: one row per kit, overwritten in place.

Nothing here validates completeness. POST /jobs is where a submission has to be whole — tag
columns belonging to the kit, at least one batch, a full plate — and those checks stay there. A
setup is a draft: if a half-finished sheet could not be saved, there would be no point to it.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Kit, KitAnalysisSetup


def save_setup(
    db: Session,
    kit: Kit,
    *,
    project_id: int | None = None,
    default_population_id: int | None = None,
    default_study_id: int | None = None,
    expected_read_number: int | None = None,
    parameters: dict | None = None,
    batches: list[dict] | None = None,
    updated_by: int | None = None,
) -> KitAnalysisSetup:
    """Upsert the kit's setup. Every field is replaced, so the caller sends the whole sheet."""
    row = kit.analysis_setup
    if row is None:
        row = KitAnalysisSetup(kit_id=kit.id)
        db.add(row)
    row.project_id = project_id
    row.default_population_id = default_population_id
    row.default_study_id = default_study_id
    row.expected_read_number = expected_read_number
    row.parameters = parameters
    row.batches = batches or []
    row.updated_by = updated_by
    db.flush()
    return row
