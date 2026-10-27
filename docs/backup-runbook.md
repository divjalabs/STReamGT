# Backup & recovery runbook

Practical steps for protecting and restoring STReamGT's data. Region is **eu-central-1**; the
database is **Neon** (PostgreSQL 16, Frankfurt, project `holy-credit-81346788`, branch
`production`); files live in S3 bucket **`streamgt-data-236726878099`**.

> Since September 2026 the database is Neon, not Aurora. The old Aurora cluster was deleted; its
> final snapshot `streamgt-db-final-20260921` is retained in RDS as a historical copy, together
> with the `pg_dump` files in `s3://streamgt-data-236726878099/backups/db/`.

## What protects the data today

| Layer | Mechanism | Notes |
|---|---|---|
| DB short-term | Neon history / branch restore | Restore the branch to an earlier moment. The free plan's window is short — check it in the Neon console before relying on it |
| DB long-term / off-cloud | `scripts/backup.sh` → `pg_dump` gzip → S3 + local copy | Portable, restorable into any Postgres. **The main protection** |
| DB accidental delete | Neon project deletion needs explicit confirmation | There is no equivalent of Aurora's deletion-protection flag |
| Files (FASTQ/results) | S3 **versioning ON** + `scripts/backup.sh` local sync | Overwrites and deletes recoverable |
| Cost control | S3 lifecycle: `uploads/` 14 d, `backups/db/` 30 d, `work/` 7 d, noncurrent versions 30 d | `backups/db/` expiring after 30 days is why the local copy matters |
| Code | Git → `github.com/divjalabs/STReamGT` | Push after committing |

**Golden rule:** run `scripts/backup.sh` before anything destructive — `alembic upgrade head` on
the live database, a bulk cleanup such as `python -m app.dedup_samples`, or `app.bootstrap --reset`
(which now refuses unless `ENVIRONMENT=development` and `STREAMGT_ALLOW_DESTRUCTIVE=yes`).

To see what a migration would change before running it:
`DATABASE_URL="<neon url>" python -m app.schemacheck`.

Because S3 expires dumps after 30 days, **keep the local copy**. The off-AWS folder
(`streamgt-backup/`, git-ignored) is the only copy that outlives that window.

---

## 1. Off-cloud backup (the one to run)

```bash
scripts/backup.sh ~/streamgt-backup
```
This: (1) runs a one-off ECS task `python -m app.dbbackup` on the `streamgt-head` task definition,
which `pg_dump`s Neon to `s3://streamgt-data-236726878099/backups/db/streamgt-<UTC>.sql.gz`, then
(2) syncs the dumps to `~/streamgt-backup/db` and (3) the data bucket (FASTQ/results, skipping
`work/` scratch) to `~/streamgt-backup/data`.

It runs in AWS rather than locally only because that machine already has `pg_dump` 16 and the
credentials; Neon itself is reachable from anywhere. The task costs about a cent.

Sanity-check a dump:
```bash
gunzip -c ~/streamgt-backup/db/streamgt-*.sql.gz | grep -c '^CREATE TABLE'   # expect ~35
```

### Dump straight from your machine (no AWS)
Needs `pg_dump` 16+ locally, or Docker:
```bash
URL=$(aws ssm get-parameter --region eu-central-1 --name /streamgt/DATABASE_URL \
        --with-decryption --query Parameter.Value --output text | sed 's/postgresql+psycopg:/postgresql:/')
docker run --rm -e URL postgres:16 sh -c 'pg_dump -d "$URL" --no-owner --no-privileges' \
  | gzip > streamgt-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
```

---

## 2. Neon's own safety net

In the Neon console, under the project's **Branches**, you can restore the `production` branch to
an earlier point in time, or create a branch from that moment to inspect it before committing.
Useful right after an accidental bulk change; useless for anything older than the plan's history
window. Treat it as a convenience, not as the backup.

---

## 3. Recovery

### Restore a `pg_dump` file into Neon
The dumps are plain SQL with `--no-owner --no-privileges`, so they load into any Postgres 16.
Restoring over a database that already has tables will fail on conflicts — restore into an empty
database or a fresh Neon branch, then repoint the app.

```bash
URL=$(aws ssm get-parameter --region eu-central-1 --name /streamgt/DATABASE_URL \
        --with-decryption --query Parameter.Value --output text | sed 's/postgresql+psycopg:/postgresql:/')
gunzip -c streamgt-<UTC>.sql.gz | docker run --rm -i -e URL postgres:16 \
  sh -c 'psql "$URL" -q -v ON_ERROR_STOP=1 --single-transaction'
```
`--single-transaction` means a failure rolls everything back and leaves the database untouched.

Verify by comparing row counts with the dump:
```bash
gunzip -c streamgt-<UTC>.sql.gz | awk '/^COPY /{t=$2;n=0;i=1;next} i&&/^\\\.$/{print t,n;i=0;next} i{n++}'
```

### Point the app at a different database
The connection URL lives in one place:
```bash
aws ssm put-parameter --region eu-central-1 --name /streamgt/DATABASE_URL \
  --type SecureString --overwrite --value 'postgresql+psycopg://<user>:<pwd>@<host>/<db>?sslmode=require'
```
Then force the Lambda to pick it up (it reads parameters at cold start only):
```bash
aws lambda update-function-configuration --region eu-central-1 --function-name streamgt-api \
  --environment "$(aws lambda get-function-configuration --region eu-central-1 --function-name streamgt-api \
      --query 'Environment.Variables' --output json \
    | python3 -c 'import json,sys,time;v=json.load(sys.stdin);v["RESTARTED_AT"]=str(int(time.time()));print(json.dumps({"Variables":v}))')"
```
The pipeline task picks up the new value on its next run; no redeploy needed.

### Recover an overwritten or deleted S3 object (versioning is on)
```bash
aws s3api list-object-versions --bucket streamgt-data-236726878099 --prefix <key> --region eu-central-1
aws s3api get-object --bucket streamgt-data-236726878099 --key <key> --version-id <VERSION> out.file --region eu-central-1
```

### The retained Aurora snapshot
`streamgt-db-final-20260921` holds the database as it was at the Neon migration. Restoring it means
creating a new Aurora cluster (`aws rds restore-db-cluster-from-snapshot`), which reintroduces an
hourly cost — so use it only to retrieve something, then delete the cluster again. The September
2026 `pg_dump` in `backups/db/` contains the same data and is far cheaper to read.

---

## Notes
- Nothing here is automated: `scripts/backup.sh` runs when you run it. If backups should be
  regular, the cheapest option is an EventBridge schedule that starts the same one-off ECS task
  (roughly a cent per run).
- Neon's free plan has a storage cap (0.5 GB) and a compute allowance; a database that grows past
  those needs a paid plan or a move back to a managed Postgres.
