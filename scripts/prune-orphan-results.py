#!/usr/bin/env python
"""Find result folders in S3 with no job row behind them, and optionally delete them.

Nothing in the application deleted S3 objects for a job until now, so every job row that went away
— a project delete, a database reset — left its results behind. On 2026-11-02 that was four
folders, 67.7 MB.

A dry run by default: it prints what it would delete and exits. Deleting needs --delete.

    cd backend
    export DATABASE_URL="<neon url>" S3_BUCKET=streamgt-data-236726878099 PYTHONPATH=.
    .venv/bin/python ../scripts/prune-orphan-results.py            # report only
    .venv/bin/python ../scripts/prune-orphan-results.py --delete   # actually remove

S3_BUCKET matters: the default in app/config.py is `streamgt-data`, while production is
`streamgt-data-236726878099`. Without it you get a bucket that does not exist, which is at least
a safe way to be wrong.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Job
from app.services import storage

PREFIX = "results/"


def orphan_prefixes() -> dict[str, tuple[int, int]]:
    """Map `results/<kit>/<public_id>/` -> (objects, bytes) for prefixes with no job row.

    Keyed on the job's public_id, which is the third path segment, because that is what
    `storage_prefix` is built from (api/jobs.py: results/{kit_code}/{public_id}).
    """
    with SessionLocal() as db:
        known = set(db.scalars(select(Job.public_id)))

    found: dict[str, tuple[int, int]] = {}
    client = storage._client()
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=settings.s3_bucket, Prefix=PREFIX
    ):
        for obj in page.get("Contents") or []:
            parts = obj["Key"].split("/")
            if len(parts) < 4:      # results/<kit>/<public_id>/<file>
                continue
            public_id = parts[2]
            if public_id in known:
                continue
            key = "/".join(parts[:3]) + "/"
            n, b = found.get(key, (0, 0))
            found[key] = (n + 1, b + obj["Size"])
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--delete", action="store_true",
                    help="actually delete; without this it only reports")
    args = ap.parse_args()

    # A clear sentence beats a botocore traceback, and the usual mistake is the bucket name.
    if not storage.bucket_exists():
        print(f"No such bucket: {settings.s3_bucket!r}.\n"
              f"Set S3_BUCKET (production is streamgt-data-236726878099).", file=sys.stderr)
        return 2

    found = orphan_prefixes()
    if not found:
        print("No orphaned result folders. Nothing to do.")
        return 0

    total_objects = sum(n for n, _ in found.values())
    total_bytes = sum(b for _, b in found.values())
    print(f"{len(found)} result folder(s) with no job row, "
          f"{total_objects} object(s), {total_bytes / 1e6:.1f} MB:\n")
    for key, (n, b) in sorted(found.items(), key=lambda kv: -kv[1][1]):
        print(f"  {b / 1e6:>8.1f} MB  {n:>3} obj  {key}")

    if not args.delete:
        print("\nDry run. Re-run with --delete to remove these.")
        return 0

    print()
    for key in found:
        n, b = storage.delete_prefix(key)
        print(f"  deleted {n:>3} object(s), {b / 1e6:>8.1f} MB  {key}")
    print(f"\nDone: {total_objects} object(s), {total_bytes / 1e6:.1f} MB freed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
