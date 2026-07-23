"""Logical database backup: pg_dump the Aurora DB and upload a gzip to S3.

Aurora is private, so this runs inside the VPC as a one-off ECS task (see scripts/backup.sh),
reusing the app.dbupgrade task pattern. The dump lands at
s3://<bucket>/backups/db/streamgt-<UTC>.sql.gz; scripts/backup.sh then syncs it (and the data
bucket) down to a local machine for an off-AWS copy.

    python -m app.dbbackup
"""
from __future__ import annotations

import gzip
import os
import subprocess
from datetime import datetime, timezone

from app.config import settings
from app.services import storage


def main() -> None:
    if not settings.db_host:
        raise SystemExit("dbbackup requires DB_HOST (runs against the deployed Postgres, not sqlite)")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"backups/db/streamgt-{ts}.sql.gz"

    env = {**os.environ, "PGPASSWORD": settings.db_password or ""}
    cmd = [
        "pg_dump", "-h", settings.db_host, "-p", str(settings.db_port),
        "-U", settings.db_user, "-d", settings.db_name,
        "--no-owner", "--no-privileges",   # portable, restorable into any local Postgres
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"pg_dump failed ({proc.returncode}): "
                         f"{proc.stderr.decode(errors='replace')[-2000:]}")

    body = gzip.compress(proc.stdout)
    storage.put_bytes(key, body, content_type="application/gzip")
    print(f"backup uploaded: s3://{settings.s3_bucket}/{key} "
          f"({len(proc.stdout):,} bytes → {len(body):,} gzip)")


if __name__ == "__main__":
    main()
