"""Logical database backup: pg_dump the deployed Postgres and upload a gzip to S3.

Runs as a one-off ECS task on the head task definition (see scripts/backup.sh), which has
pg_dump 16 and the DB credentials. The dump lands at
s3://<bucket>/backups/db/streamgt-<UTC>.sql.gz; scripts/backup.sh then syncs it (and the data
bucket) down to a local machine for an off-AWS copy.

    python -m app.dbbackup
"""
from __future__ import annotations

import gzip
import subprocess
from datetime import datetime, timezone

from app.config import settings
from app.services import storage


def main() -> None:
    url = settings.resolved_database_url
    if not url.startswith("postgresql"):
        raise SystemExit("dbbackup requires a Postgres DATABASE_URL (not sqlite)")
    libpq_url = url.replace("postgresql+psycopg://", "postgresql://", 1)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"backups/db/streamgt-{ts}.sql.gz"

    cmd = [
        "pg_dump", "-d", libpq_url,
        "--no-owner", "--no-privileges",   # portable, restorable into any local Postgres
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"pg_dump failed ({proc.returncode}): "
                         f"{proc.stderr.decode(errors='replace')[-2000:]}")

    body = gzip.compress(proc.stdout)
    storage.put_bytes(key, body, content_type="application/gzip")
    print(f"backup uploaded: s3://{settings.s3_bucket}/{key} "
          f"({len(proc.stdout):,} bytes → {len(body):,} gzip)")


if __name__ == "__main__":
    main()
