"""Set/replace a kit's current server-side FASTQ pair (one per kit)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Kit, KitReads
from app.services import storage


def set_kit_reads(
    db: Session,
    kit: Kit,
    *,
    fastq1_key: str,
    fastq2_key: str,
    fastq1_name: str | None = None,
    fastq2_name: str | None = None,
    size1: int | None = None,
    size2: int | None = None,
    uploaded_by: int | None = None,
) -> KitReads:
    """Upsert the kit's reads to this pair, deleting any previous objects it replaces."""
    new_keys = {fastq1_key, fastq2_key}
    existing = kit.reads
    old_keys = [k for k in ((existing.fastq1_key, existing.fastq2_key) if existing else ())
                if k not in new_keys]
    if existing is None:
        existing = KitReads(kit_id=kit.id)
        db.add(existing)
    existing.fastq1_key, existing.fastq2_key = fastq1_key, fastq2_key
    existing.fastq1_name, existing.fastq2_name = fastq1_name, fastq2_name
    existing.size1, existing.size2 = size1, size2
    existing.uploaded_by = uploaded_by
    db.flush()
    for key in old_keys:      # remove the superseded pair (best-effort)
        storage.delete_object(key)
    return existing
