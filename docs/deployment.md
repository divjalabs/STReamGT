# STReamGT — Production Deployment Plan (AWS, single VM)

This is the step-by-step plan to take STReamGT from the local dev setup to a running
production service on AWS: one Docker host (EC2) running the web app + Celery worker +
Nextflow, **S3** for storage, **SES** for email, optional **RDS** for Postgres.

It also fixes the one real production gotcha in the current compose file — the
**worker ↔ Docker path mismatch** (Phase 4). Read that before first launch.

---

## 0. Decisions & prerequisites

| Item | Recommendation | Notes |
|---|---|---|
| Region | `eu-central-1` (Frankfurt) | Close to EU labs; keep S3+EC2+SES in one region. |
| Domain | e.g. `streamgt.yourlab.org` | Needed for HTTPS (Caddy auto-TLS) and SES. |
| Instance | `c6i.2xlarge` (8 vCPU / 16 GB) to start | OBITools pairing on ~28M reads is CPU-bound; size up if jobs are slow. |
| Disk | 200 GB gp3 EBS | A 2 GB FASTQ expands a lot in the OBITools work dir; jobs run for hours. |
| Postgres | Start containerized; move to **RDS** for real use | RDS gives backups/HA without ops. |
| Concurrency | 1–2 jobs at once (worker `--concurrency`) | Each job is heavy; don't oversubscribe the VM. |

Accounts/tools: an AWS account with permissions for EC2, S3, IAM, SES (and RDS if used);
a registered domain you can point at the VM; `docker` + `docker compose` on the VM.

---

## 1. Provision AWS infrastructure

### 1a. S3 bucket (storage)
```bash
aws s3api create-bucket --bucket streamgt-data \
  --region eu-central-1 --create-bucket-configuration LocationConstraint=eu-central-1
aws s3api put-public-access-block --bucket streamgt-data \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket streamgt-data \
  --versioning-configuration Status=Enabled   # protects against accidental overwrite/delete
```
CORS (required so the browser can PUT FASTQ parts directly and read ETag):
```json
[{
  "AllowedOrigins": ["https://streamgt.yourlab.org"],
  "AllowedMethods": ["PUT","GET"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["ETag"],
  "MaxAgeSeconds": 3000
}]
```
```bash
aws s3api put-bucket-cors --bucket streamgt-data --cors-configuration file://cors.json
```
Optional lifecycle: expire `uploads/` after N days (raw FASTQ is large), keep `results/`.

### 1b. IAM (least privilege)
Create an **EC2 instance role** (preferred over static keys) with an inline policy scoped to
the bucket: `s3:PutObject,GetObject,DeleteObject,ListMultipartUploadParts,AbortMultipartUpload`
on `arn:aws:s3:::streamgt-data/*` and `s3:ListBucket` on the bucket. Attaching the role to the
instance means you can leave `AWS_ACCESS_KEY_ID`/`SECRET` **empty** in `.env` (boto3 uses the
role automatically).

### 1c. EC2 instance + security group
- Launch the instance from Ubuntu 22.04, attach the IAM role, 200 GB gp3.
- Security group inbound: `443` and `80` from `0.0.0.0/0` (Caddy/TLS), `22` from your IP only.
- Allocate an **Elastic IP** and associate it (stable address for DNS).

### 1d. SES (email)
- Verify the domain (or at least `no-reply@streamgt.yourlab.org`) in SES.
- Request **production access** (SES starts in sandbox — can only send to verified addresses).
- Create **SMTP credentials** (SES → SMTP settings). You'll use host
  `email-smtp.eu-central-1.amazonaws.com`, port `587`, TLS on.

### 1e. (Optional) RDS Postgres
- Create a `db.t4g.small` Postgres 16 instance, same VPC/SG, not publicly accessible.
- Note the endpoint for `DATABASE_URL`.

---

## 2. Prepare the VM

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # re-login after this

# Code
git clone <your-repo-url> streamgt && cd streamgt

# Build the pipeline's OBITools image on the host (the worker drives the host daemon)
docker build -t stream:latest pipeline/
```

---

## 3. Configure environment & secrets

```bash
cp .env.example .env
```
Set in `.env` (generate `SECRET_KEY` with `python -c "import secrets;print(secrets.token_urlsafe(48))"`):
```ini
ENVIRONMENT=production
FRONTEND_BASE_URL=https://streamgt.yourlab.org
SECRET_KEY=<random>
DATABASE_URL=postgresql+psycopg://streamgt:<pw>@postgres:5432/streamgt   # or the RDS endpoint
REDIS_URL=redis://redis:6379/0
S3_BUCKET=streamgt-data
S3_REGION=eu-central-1
S3_ENDPOINT_URL=            # empty = real AWS
AWS_ACCESS_KEY_ID=          # empty if using the instance IAM role
AWS_SECRET_ACCESS_KEY=
SMTP_HOST=email-smtp.eu-central-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=<ses-smtp-user>
SMTP_PASSWORD=<ses-smtp-pass>
SMTP_USE_TLS=true
EMAIL_FROM=no-reply@streamgt.yourlab.org
NEXTFLOW_PROFILE=docker
JOB_SCRATCH_ROOT=/opt/streamgt/scratch      # see Phase 4 — must be a host path
```
Never commit `.env`. For stronger secret hygiene, use AWS SSM Parameter Store / Secrets
Manager and inject at boot instead of a file.

---

## 4. ⚠️ Fix the worker ↔ Docker path mismatch (do this before first launch)

The worker container runs `nextflow -profile docker`, which calls the **host** Docker daemon
(via the mounted socket) to launch each `stream:latest` process. The host daemon bind-mounts
the task work dir **by its host path**. If the worker's scratch is a *named volume*
(`scratch:/scratch`), that path doesn't exist on the host → the process container sees empty
inputs and the job fails.

**Fix: bind-mount the scratch dir at the *same absolute path* on host and in the worker**, and
point `JOB_SCRATCH_ROOT` at it. Edit `deploy/docker-compose.yml` worker service:
```yaml
  worker:
    build: { context: .., dockerfile: deploy/Dockerfile.worker }
    env_file: ../.env
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/streamgt/scratch:/opt/streamgt/scratch   # SAME path both sides (required)
```
```bash
sudo mkdir -p /opt/streamgt/scratch && sudo chown $USER /opt/streamgt/scratch
```
Now Nextflow work dirs live under `/opt/streamgt/scratch/...`, an identical path on host and in
the container, so the host daemon's bind-mounts resolve. (Alternative if you dislike DooD: run
the Celery worker as a **host process** in a venv — Nextflow + Docker then share the host FS
natively. The compose worker is simpler to operate, so prefer the bind-mount fix.)

---

## 5. Launch, migrate, seed

```bash
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps       # all healthy?

# DB schema (the api service runs `alembic upgrade head` on start; generate the first
# migration once if you haven't):
docker compose -f deploy/docker-compose.yml exec api alembic revision --autogenerate -m init
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head

# First admin
docker compose -f deploy/docker-compose.yml exec api \
  python -m app.bootstrap --admin-email you@lab.org --admin-password '<strong>'
```
Then register kits (see `docs/kit-onboarding.md`): upload each species' primers CSV +
`tags.csv` to S3, `POST /api/kits` with the keys. The tags CSV **must** be in S3 (its
positional tag values can't be rebuilt from the DB).

---

## 6. DNS + TLS

- Point an `A` record for `streamgt.yourlab.org` at the Elastic IP.
- Set the caddy service address to your domain (env `SITE_ADDRESS=streamgt.yourlab.org` in the
  compose caddy service). Caddy fetches a Let's Encrypt cert automatically on first request.
- Confirm `https://streamgt.yourlab.org/health` returns `{"status":"ok"}`.

---

## 7. End-to-end verification (production smoke)

1. Register a normal user in the UI; confirm you can log in.
2. Admin registers the DIVJA240 kit.
3. Submit a job: upload a **small subsampled FASTQ pair** first (fast), two batches
   (HRM01→PP1-PP4, HRM02→PP5-PP8).
4. Watch `docker compose logs -f worker`: expect `staging → running (nextflow) → uploading →
   succeeded`, one `stream:latest` container per process on `docker ps`.
5. Confirm the completion **email** arrives (SES) and results/report **download** works
   (presigned S3 links).
6. Then run one **full 2 GB** job to validate real memory/time and disk headroom.

---

## 8. Operations

- **Backups**: RDS automated snapshots (or a nightly `pg_dump` cron to S3 for the containerized
  DB). S3 versioning already protects result objects.
- **Logs**: `docker compose logs`; ship to CloudWatch with the awslogs driver if you want
  retention/alerts. Nextflow per-job logs live under the job's scratch dir (kept on failure,
  cleaned on success by the worker — change that if you want to always retain them).
- **Updates**: `git pull && docker compose up --build -d`. Rebuild `stream:latest` only when
  `pipeline/` changes. Run `alembic upgrade head` after model changes.
- **Disk hygiene**: cron to prune old scratch dirs and `docker system prune -f`; S3 lifecycle
  for `uploads/`.
- **Monitoring**: a simple uptime check on `/health`; alert if the worker queue backs up
  (Redis `LLEN`) or disk >80%.

---

## 9. Security hardening

- Objects private; **presigned URLs only**, short TTL (`PRESIGN_EXPIRE_SECONDS`).
- Per-user S3 prefixes (`uploads/{user_id}/…`) already enforced server-side; jobs are
  ownership-checked (`_get_owned_job`).
- Secrets via IAM role + Secrets Manager, not committed files.
- SG: 22 restricted to your IP (or SSM Session Manager, no inbound SSH at all).
- Rate-limit `/api/auth/*` (add slowapi or a Caddy rate-limit) to slow credential stuffing.
- Keep the OS patched; enable automatic security updates.

---

## 10. Scale-up path (when one VM isn't enough)

- **AWS Batch executor**: add a `batch` profile to `pipeline/nextflow.config` (queue + compute
  environment + job role with S3 access) and set `NEXTFLOW_PROFILE=batch`. Jobs then autoscale
  on Batch and scale to zero when idle — **no app code changes** (the worker just launches
  Nextflow with a different profile). This removes the single-VM CPU/disk ceiling and the
  DooD path issue entirely.
- **Separate worker host**: keep the web tier small and run the worker on a bigger/spot
  instance; they share Postgres + Redis + S3.
- **Managed orchestration**: Seqera Platform (Nextflow Tower) for launch/monitoring/history if
  you'd rather not operate the worker yourself.

---

## Rough monthly cost (starting point, eu-central-1, on-demand)

| Component | Est. |
|---|---|
| EC2 c6i.2xlarge (24×7) | ~$250 |
| 200 GB gp3 EBS | ~$18 |
| RDS db.t4g.small (optional) | ~$30 |
| S3 (100 GB + requests) | ~$3–10 |
| SES | ~$0 (first 62k emails free from EC2) |
| **Total** | **~$300/mo** (much less if you stop the VM when idle or move to Batch) |

Biggest lever: if jobs are bursty, run compute on **AWS Batch/spot** and keep only a small
always-on web VM — can cut compute cost by 50–80%.
```
