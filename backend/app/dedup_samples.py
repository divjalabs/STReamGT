"""One-off: remove samples duplicated by past kit reanalyses.

    python -m app.dedup_samples

Idempotent (a second run finds no duplicates). Run once after deploying the ingestion fix.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.services.sample_dedup import dedup_duplicate_samples


def main() -> None:
    with SessionLocal() as db:
        summary = dedup_duplicate_samples(db)
        db.commit()
    print(f"dedup complete: {summary['deleted']} duplicate sample(s) removed across "
          f"{summary['groups']} group(s); matching purged for {summary['pops_purged']} population(s)")


if __name__ == "__main__":
    main()
