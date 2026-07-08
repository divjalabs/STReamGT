# STReamGT Web Platform — Architecture & Build Plan

## Context

`STReamGT` is a working Nextflow DSL2 pipeline that genotypes STR/SNP markers from
paired-end amplicon FASTQ (OBITools4 + custom Python allele callers). Today it is run
manually from a shell on an on-prem Singularity server (`obitools4_py.sif` on "Ribica"),
driven entirely by a **`input.tsv` samplesheet** whose columns are:

```
kit_id  sample_path(.xlsx)  tags(e.g. PP1-PP4)  tags_path(.csv)  primers_path(.csv)  fastq1_path  fastq2_path
```

The goal is a **web application** so lab users can: register/log in, upload ~2 GB FASTQ,
submit a genotyping job (choosing kit + samples + tags/primers), track progress by job ID,
get an email when it finishes, download genotypes + the QC report, and browse history.

The pipeline is already the hard part and works. **The web app is essentially a thin
"input assembler + job runner + result harvester" wrapped around `nextflow run`.** The
whole design pivots on one insight: everything the pipeline needs is `input.tsv` + the files
it points at. The app's job is to produce that samplesheet from UI inputs, stage the
referenced files, launch Nextflow, then collect `${kit_id}/results` + `${kit_id}/reports`
and render `Genotype_stat.Rmd`.

### Decisions (confirmed with user)
- **Storage:** **AWS S3** for FASTQ + results. Storage/compute kept decoupled so the executor can change later.
- **Compute:** a **single cloud VM with Docker** runs everything (web + worker + `nextflow run -profile docker`). The on-prem Ribica server is **not** usable here — it has no Docker and no sudo rights. (Managed AWS Batch is the later scale-up path — see Alternatives.)
- **Kits:** **admin-curated kit catalog** in the DB. A kit ID owns its **primers, tag set (PP1–PP8), and controls**. Users pick a kit; admins register it once.
- **Job shape:** **one FASTQ pair per job** (one sequencing run), shared by all sample batches. A job = kit + FASTQ pair + N **sample batches (amplification plates)**, each batch = a sample `.xlsx` + a **selected subset of PP tag columns** (e.g. HRM01→PP1-PP4, HRM02→PP5-PP8). Tag *columns* are selected/verified per batch; tag *sequences* are not edited (they live in the kit's tags CSV).
- **Stack:** **FastAPI + Postgres + Celery/Redis** backend, lightweight React (or server-rendered) frontend, all in Docker on the one VM.

---

## Target Architecture

```
                          ┌─────────────────────────────────────────┐
 Browser ──HTTPS──▶  Reverse proxy (Caddy/nginx, TLS)                 │
                          │                                           │
                          ▼                                           │
                 FastAPI web/API  ──────────────┐                     │
                  - auth (JWT/session)           │ enqueue job        │
                  - kit catalog CRUD (admin)     ▼                     │
                  - job submit/status         Redis (broker) ◀──┐     │
                  - presigned upload URLs         │             │     │
                  - result download URLs          ▼             │     │
                          │              Celery worker(s) ───────┘     │
                          │                  │  runs: nextflow run main.nf --input input.tsv
                          ▼                  │        -profile docker|singularity
                     Postgres                │  renders Genotype_stat.Rmd
             users · kits · jobs · results   │  sends completion email (SMTP/SES)
                          ▲                  ▼
                          └──────── Object storage (S3): raw/  results/  reports/
```

- **Uploads** go **browser → S3 directly** via presigned multipart URLs (never through the API server) — essential for 2 GB files. The API only records metadata.
- **Job execution** is async: submit returns a `job_id` immediately; a Celery worker does the multi-hour work; status is polled/streamed.
- **Storage** is the durable source of truth for large files; Postgres holds only metadata + small result tables.

---

## Repository / Folder Reorganization

Convert the repo into a monorepo. **The existing pipeline moves unchanged into `pipeline/`** so `nextflow run` keeps working; new code lives alongside.

```
STReamGT/
├── pipeline/                     # ← existing pipeline, moved as-is
│   ├── main.nf
│   ├── nextflow.config           # add resource + s3/batch profiles here
│   ├── modules/                  # unchanged
│   ├── bin/                      # make_ngsfilter.py, callAlleleUL.py, parameters.json
│   ├── Dockerfile                # existing OBITools4 image (stream:latest)
│   ├── requirements.txt
│   └── assets/
│       ├── nextflow_schema.json  # NEW: validate params (currently none)
│       └── report/Genotype_stat.Rmd  # ← moved here, parameterized
│
├── backend/                      # FastAPI app
│   ├── app/
│   │   ├── main.py               # FastAPI entrypoint
│   │   ├── api/                  # routers: auth, kits, jobs, results
│   │   ├── models/               # SQLAlchemy: User, Kit, Primer, TagSet, Job, ResultFile
│   │   ├── schemas/              # Pydantic request/response
│   │   ├── services/
│   │   │   ├── storage.py        # S3 presign upload/download
│   │   │   ├── samplesheet.py    # build input.tsv from job + kit
│   │   │   └── notify.py         # email on completion
│   │   ├── worker/
│   │   │   ├── celery_app.py
│   │   │   └── tasks.py          # run_pipeline(job_id): stage → nextflow → harvest → email
│   │   ├── auth/                 # password hashing, JWT, RBAC (user/admin)
│   │   └── db.py
│   ├── alembic/                  # DB migrations
│   ├── tests/
│   ├── Dockerfile                # api + worker (worker also needs Nextflow + Docker/Singularity)
│   └── pyproject.toml
│
├── frontend/                     # React (Vite) or server-rendered templates
│   ├── src/{pages,components,api}/
│   └── Dockerfile
│
├── deploy/
│   ├── docker-compose.yml        # local/single-VM: proxy, api, worker, postgres, redis
│   ├── docker-compose.prod.yml
│   └── caddy/Caddyfile           # TLS + reverse proxy
│
├── docs/
│   ├── architecture.md           # this design + the excalidraw diagrams
│   └── kit-onboarding.md         # how admins register a kit
│
├── .env.example                  # secrets: DB, S3 keys, SMTP, JWT
└── README.md                     # NEW (none exists today)
```

Cleanup during the move: drop machine-specific `input.tsv`, `.RData`/`.Rhistory`,
`work/`, `.nextflow/`; keep `DIVJA240/` as a fixture under `pipeline/tests/`.

---

## Data Model (Postgres)

- **User** — id, email (login), password_hash, organisation, role (`user`/`admin`), created_at, (optional subscription_expires — the excalidraw "subscription for 1 month?").
- **Kit** — id, kit_code, species, description, owner/visibility, created_by. A kit **has many**:
  - **Primer** — locus, type (`microsat`/`snp`), primerF, primerR, motif, sequence. (Content of the primers CSV, e.g. `UA_primers.csv`.)
  - **TagColumn** — the PP columns (`PP1`…`PP8`) parsed from the kit's tags CSV header (e.g. `wolf_tags1.csv`). The kit stores the canonical tags CSV (S3 key); the app reads its header to know which PPs exist. These are the columns a user selects among per batch.
  - **Control** — name pattern for negatives/positives (maps to `parameters.json` `negative_name`, default `"blank"`).
- **Job** — id (public job_id), user_id, kit_id, status (`queued/staging/running/rendering/succeeded/failed`), created_at, started_at, finished_at, nextflow_run_name, storage_prefix, error_message, **fastq1 key, fastq2 key** (one pair, job-level, shared by all batches), params (min_identity, min_overlap, expected_read_number). A job **has many**:
  - **SampleBatch** (amplification plate) — sample_sheet(.xlsx) object key, **selected PP columns** (e.g. `["PP5","PP6","PP7","PP8"]`, serialized to the `tags` range string `PP5-PP8` for the samplesheet). One `SampleBatch` → one `input.tsv` row. Supports the excalidraw "possibly multiple AP" and "add multiple sample batches per kit manually".
  - **ResultFile** — kind (`genotypes/positions/frequency/reads_summary/html_report`), object key, size.

Note the FASTQ keys live on **Job**, not **SampleBatch** — every generated `input.tsv` row repeats the job's FASTQ pair (exactly as the current `input.tsv` does; the pipeline's `.take(1)` uses one pair). This mirrors the excalidraw "DATABASES" block (user data / kit / job id).

---

## End-to-End Workflow

1. **Register / log in** → JWT session. Admin role gated for kit management.
2. **Admin registers a kit** (once): upload/enter primers, tag layout, controls → stored as `Kit` + children. This replaces today's loose `primers_tags/*.csv` files.
3. **Submit a job (wizard):**
   - Pick kit ID (→ primers, controls, and the available PP tag columns auto-attached from the kit).
   - Upload the **one FASTQ pair (R1/R2)** for the run — **presigned multipart S3 upload from the browser**, resumable (essential for ~2 GB).
   - Add **one or more sample batches** (the "add multiple sample batches manually" UI): for each batch, upload its sample `.xlsx` and **select/verify which PP columns apply** to that batch (checkbox list rendered from the kit's PP1–PP8; e.g. HRM01→PP1-PP4, HRM02→PP5-PP8). No FASTQ per batch — it's shared.
   - Optional: expected read number (for the report), min_identity/min_overlap.
   - Submit → row in `Job` (status `queued`), returns **job_id**. Frontend shows a "sequencing QC / progress" view.
4. **Worker runs the job** (`backend/app/worker/tasks.py::run_pipeline`):
   - Create a scratch workdir; download the job's inputs from S3.
   - Materialize the kit's primers CSV + tags CSV; write `input.tsv` via `services/samplesheet.py` — **one row per SampleBatch**, each row = (kit_id, that batch's `.xlsx`, the batch's PP range e.g. `PP5-PP8`, kit tags CSV, kit primers CSV, job FASTQ1, job FASTQ2). FASTQ + primers/tags are identical across rows; only sample sheet + tag range differ (exactly the shape of the current `input.tsv`). Uses local staged paths — fixing today's hard-coded absolute paths.
   - `nextflow run pipeline/main.nf --input input.tsv -profile <docker|singularity> --outdir <prefix>`; stream `.nextflow.log` → job status/progress.
   - On success: render `Genotype_stat.Rmd` (params = the produced CSV/TXT) to HTML; upload `results/*` + `reports/*` + the HTML report to S3; write `ResultFile` rows.
   - Update status; **send completion email** (link to results). On failure: capture Nextflow error, status `failed`, email the failure.
5. **Track progress** — `GET /jobs/{job_id}` returns status + step; optional live log tail (SSE/WebSocket).
6. **Download / history** — results list with presigned download URLs; the HTML QC report viewable inline; all past jobs listed per user.

### Pipeline changes needed to run headlessly (small, in `pipeline/`)
- Fix `CREATE_SUMMARY` raw-FASTQ input: pass `file(row.fastq1_path)`, not the bare string (current `Not a valid path value` bug in `drafts`).
- Add resource/executor config + an `s3`/`batch` profile to `nextflow.config` (currently profiles-only, 1 cpu default).
- Add `assets/nextflow_schema.json` for param validation (none today).
- Parameterize `Genotype_stat.Rmd` inputs (already uses `params:`) and wire it as a render step (currently standalone/manual).
- Keep `--take(1)` assumption honored by the samplesheet builder (one FASTQ pair + one primer set per job), or generalize later per the excalidraw "multiple AP" TODO.

---

## Cloud / Deployment (recommended path)

- **Phase-1 (test on one machine — the chosen path):** a **single cloud VM (e.g. EC2) with Docker** running `deploy/docker-compose.prod.yml` — Caddy + FastAPI + Celery worker + Postgres + Redis. The worker runs `nextflow run -profile docker` **on that same VM** (uses the pipeline's existing `stream:latest` Docker image — no Singularity, since Ribica lacks Docker/sudo). Objects in **S3**; email via **SES/SMTP**. Size the VM for the pipeline's real needs (multi-core + enough RAM/disk for a 2 GB FASTQ + OBITools work dir); keep FASTQ on S3 and stage to a local scratch volume per job. Managed Postgres (RDS) optional.
- **Scale-up path:** switch the Nextflow executor to **AWS Batch** (add a `batch` profile; jobs autoscale, scale-to-zero) without changing the app — the worker just launches Nextflow with a different profile. This is why storage/compute are decoupled.
- **Security:** presigned URLs (time-limited), objects private, per-user prefix isolation, secrets in env/secret manager, HTTPS only, rate-limit auth.

---

## Build Order (milestones)

1. **Repo reshape** — move pipeline into `pipeline/`, add `backend/ frontend/ deploy/ docs/`, add README; fix the `CREATE_SUMMARY` bug; verify `nextflow run` still works from the new path.
2. **Core backend** — FastAPI skeleton, Postgres + Alembic, User/Kit/Job models, auth (register/login).
3. **Kit catalog** — admin CRUD for kits/primers/tags/controls (Django-admin-style page if using Django; otherwise a simple admin UI).
4. **Storage + uploads** — S3 presigned multipart upload; job submission wizard persists plates + object keys.
5. **Worker** — `run_pipeline` task: stage → build `input.tsv` → `nextflow run` → harvest → render Rmd → upload → email. Status transitions + log capture.
6. **Frontend** — auth pages, submit wizard, job list + detail/progress, results/report download.
7. **Notifications + history** — email templates; historical results browsing.
8. **Deploy** — docker-compose on the VM/Ribica, TLS, backups; (optional) AWS Batch profile.

---

## Verification

- **Pipeline still runs after move:** from `pipeline/`, `nextflow run main.nf --input tests/DIVJA240/input.tsv -profile docker` produces `results/*_genotypes.txt` + `reports/*_reads_summary.csv` identical to the committed `DIVJA240/` fixture.
- **Samplesheet builder:** unit-test `services/samplesheet.py` — given a Job + Kit, it emits a 7-column TSV with valid staged paths; assert Nextflow accepts it.
- **End-to-end (staging):** register user → admin adds the `DIVJA240` wolf kit (UA_primers + wolf_tags1 PP1–PP8 + `blank` control) → submit a job with the fixture FASTQ (or a subsampled ~50 MB pair for speed) and **two sample batches** — HRM01 with PP1-PP4, HRM02 with PP5-PP8 — reproducing the current `input.tsv` → poll job to `succeeded` → download genotypes + HTML report → confirm completion email received (MailHog locally). The generated `input.tsv` should be byte-equivalent (modulo paths) to the committed one.
- **Upload path:** upload a 2 GB test file via presigned multipart from the browser; confirm it lands in S3 and never transits the API container (watch API memory).
- **Auth/RBAC:** non-admin cannot reach kit-management endpoints; users see only their own jobs.

---

## Alternatives (not chosen; switch points noted)
- **Compute:** AWS Batch / Google Batch (autoscale) instead of a worker VM — better at scale, more IAM/infra work. Add as a Nextflow profile later; app code unchanged.
- **Stack:** Django instead of FastAPI — gains a built-in admin panel (nice for the kit catalog) and auth, at some async cost.
- **Kits:** user-uploaded primer/tag files per job (no catalog) — more flexible, more error-prone; or hybrid (catalog + custom).
- **Managed orchestration:** Seqera Platform (Nextflow Tower) can provide job launching/monitoring/history out of the box — reduces custom worker/monitoring code if you're willing to adopt it.
