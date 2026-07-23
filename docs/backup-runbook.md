# Backup & recovery runbook

Practical steps for protecting and restoring STReamGT's data. Region is **eu-central-1**; the DB is
Aurora PostgreSQL cluster **`streamgt-db`**; files live in S3 bucket **`streamgt-data-236726878099`**.

## What protects the data today

| Layer | Mechanism | Notes |
|---|---|---|
| DB point-in-time | Aurora automated backups, **14-day** retention | rewind to any second in the window |
| DB accidental delete | **Deletion protection ON** | cluster can't be deleted without disabling it first |
| DB long-term / off-AWS | `scripts/backup.sh` → `pg_dump` gzip + local copy | portable, restorable anywhere |
| Files (FASTQ/results) | S3 **versioning ON** + `scripts/backup.sh` local sync | overwrites/deletes recoverable |
| Cost control | S3 lifecycle: `uploads/` 14d, `backups/db/` 30d, noncurrent versions 30d | — |
| Code | Git → `github.com/divjalabs/STReamGT` | push after committing |

> Not yet done: **Aurora storage-at-rest encryption** (needs a snapshot→restore re-create).

**Golden rule:** run a manual snapshot **and** `scripts/backup.sh` before anything destructive —
`python -m app.bootstrap --reset`, a schema migration, or the encryption cutover.

---

## 1. Manual DB snapshot (in-AWS, point-in-time)

Free, ~1–3 min. Unlike the automated 14-day snapshots, manual ones persist until you delete them.

### Take it (label with the date)
```bash
aws rds create-db-cluster-snapshot --region eu-central-1 \
  --db-cluster-identifier streamgt-db \
  --db-cluster-snapshot-identifier streamgt-db-manual-2026-07-23
```
Identifier rules: letters/numbers/hyphens, must start with a letter, must be unique. A date (or
`-before-migration`) suffix keeps them tidy.

### Wait until ready
```bash
aws rds wait db-cluster-snapshot-available --region eu-central-1 \
  --db-cluster-snapshot-identifier streamgt-db-manual-2026-07-23 && echo "snapshot ready"
```

### List your snapshots
```bash
aws rds describe-db-cluster-snapshots --region eu-central-1 \
  --db-cluster-identifier streamgt-db --snapshot-type manual \
  --query 'DBClusterSnapshots[].{id:DBClusterSnapshotIdentifier,status:Status,created:SnapshotCreateTime}' \
  --output table
```

### Console alternative
RDS → **Databases** → `streamgt-db` → **Actions → Take snapshot** → name it. Find later under RDS →
**Snapshots → Manual**.

---

## 2. Off-AWS backup to your machine

```bash
scripts/backup.sh ~/streamgt-backup
```
This: (1) runs a one-off ECS task `python -m app.dbbackup` that `pg_dump`s the DB to
`s3://streamgt-data-236726878099/backups/db/streamgt-<UTC>.sql.gz`, then (2) `aws s3 sync`s the DB
dumps to `~/streamgt-backup/db` and (3) the data bucket (FASTQ/results, skipping `work/` scratch) to
`~/streamgt-backup/data`.

Sanity-check a dump:
```bash
gunzip -c ~/streamgt-backup/db/streamgt-*.sql.gz | grep -c '^CREATE TABLE'
```

---

## 3. Recovery

### Restore a `pg_dump` file (fastest for logical/corruption recovery)
Into any target Postgres (a fresh cluster, or a local one for inspection):
```bash
gunzip -c streamgt-<UTC>.sql.gz | psql "postgresql://<user>:<pass>@<host>:5432/<dbname>"
```

### Restore a cluster snapshot (full point-in-time)
You restore into a **new** cluster, then repoint the app — you don't restore over the live one:
```bash
aws rds restore-db-cluster-from-snapshot --region eu-central-1 \
  --db-cluster-identifier streamgt-db-restored \
  --snapshot-identifier streamgt-db-manual-2026-07-23 \
  --engine aurora-postgresql
# then: add a DB instance to the new cluster, and update the streamgt-api task-def DB_HOST
# to the new writer endpoint (new task-def revision -> update-service).
```
The restored cluster keeps the source master credentials, so `DB_PASSWORD` stays valid — only
`DB_HOST` changes.

### Recover an overwritten/deleted S3 object (versioning is on)
```bash
aws s3api list-object-versions --bucket streamgt-data-236726878099 --prefix <key> --region eu-central-1
aws s3api get-object --bucket streamgt-data-236726878099 --key <key> --version-id <VERSION> out.file --region eu-central-1
```

---

## Notes
- Deletion protection means an *intentional* teardown must first run
  `aws rds modify-db-cluster --db-cluster-identifier streamgt-db --no-deletion-protection`.
- Snapshots inherit the cluster's encryption state; once the DB is encrypted, snapshots are too.
</content>
