# Deploying STReamGT (single VM)

The whole stack runs on one Docker host (cloud VM). Compose services:
`postgres`, `redis`, `api` (FastAPI), `worker` (Celery + Nextflow + R), `caddy` (TLS proxy),
plus dev-only `minio` (S3) and `mailhog` (SMTP). In production, point `S3_*` at real AWS and
SMTP at SES, and drop the `minio`/`mailhog` services.

## Prerequisites
- Docker + Docker Compose on the VM.
- The pipeline's OBITools image built and available to the host Docker:
  ```bash
  docker build -t stream:latest pipeline/
  ```
  The worker mounts `/var/run/docker.sock`, so Nextflow's `-profile docker` launches
  `stream:latest` via the host daemon.

## First run
```bash
cp .env.example .env         # then edit secrets (SECRET_KEY, AWS creds or MinIO, SMTP)
docker compose -f deploy/docker-compose.yml up --build -d

# Create the S3 bucket (MinIO dev): open http://localhost:9001 (minioadmin/minioadmin)
# and create the bucket named in S3_BUCKET, or with the mc client.

# Create the first admin user:
docker compose -f deploy/docker-compose.yml exec api \
  python -m app.bootstrap --admin-email you@lab.org --admin-password 'strong-pass'
```
- API docs: `http://localhost:8000/docs`
- MailHog (dev emails): `http://localhost:8025`

## S3 / MinIO CORS (required for browser uploads)
The browser PUTs FASTQ parts directly to the bucket, so it must allow the app origin and
**expose the `ETag` header** (multipart completion needs it). Example CORS rule:
```json
[{
  "AllowedOrigins": ["https://your.domain", "http://localhost:5173"],
  "AllowedMethods": ["PUT", "GET"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["ETag"],
  "MaxAgeSeconds": 3000
}]
```

## Production notes
- Set `SITE_ADDRESS=your.domain` for the caddy service (env) to get automatic HTTPS.
- Use managed Postgres (RDS) and real S3; put secrets in the VM's secret store, not `.env`.
- Size the VM for the pipeline: several vCPUs, enough RAM for OBITools, and a large
  `scratch` volume (a 2 GB FASTQ expands during processing).
- Scale-up path: switch the Nextflow executor to AWS Batch by adding a `batch` profile to
  `pipeline/nextflow.config` and setting `NEXTFLOW_PROFILE=batch` — no app code changes.

## End-to-end smoke (DIVJA240 fixture)
1. Admin registers the `DIVJA240` kit (see `docs/kit-onboarding.md`), uploading
   `STReam_primers_tags/UA_primers.csv` and `tags.csv`.
2. A user submits a job: one FASTQ pair + two batches (HRM01→PP1-PP4, HRM02→PP5-PP8).
3. Watch `docker compose logs -f worker`; on success the user gets an email and the
   results/report appear for download.
