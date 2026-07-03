# STReamGT

STR/SNP genotyping platform: a **Nextflow pipeline** (OBITools4 + custom allele callers)
plus a **web application** that lets lab users submit genotyping jobs, track progress,
and download genotypes + QC reports.

## Monorepo layout

```
STReamGT/
├── pipeline/     Nextflow DSL2 pipeline (main.nf, modules/, bin/, Dockerfile)
│   └── assets/report/Genotype_stat.Rmd   QC/visualization report
├── backend/      FastAPI + Celery worker + SQLAlchemy models (users, kits, jobs)
├── frontend/     React (Vite) web UI (auth, submit wizard, job tracking)
├── deploy/       docker-compose + Caddy for a single-VM deployment
└── docs/         architecture.md, kit-onboarding.md
```

## The pipeline in one paragraph

Everything the pipeline needs is a **tab-separated `input.tsv`** samplesheet plus the
files it references:

```
kit_id  sample_path(.xlsx)  tags(e.g. PP1-PP4)  tags_path(.csv)  primers_path(.csv)  fastq1_path  fastq2_path
```

One row per **sample batch** (amplification plate). All rows in a run share one FASTQ pair
and one primer/species set. The pipeline demultiplexes by tags, splits by locus, calls
alleles in parallel, and publishes `${kit_id}/results/*_genotypes.txt` and
`${kit_id}/reports/*_reads_summary.csv`.

### Run the pipeline directly

```bash
cd pipeline
nextflow run main.nf --input tests/input.example.tsv -profile docker
```

## The web app in one paragraph

The web app is a thin **input assembler + job runner + result harvester** around
`nextflow run`. Admins register **kits** (primers, PP1–PP8 tag columns, controls, species)
once. Users pick a kit, upload one FASTQ pair (direct-to-S3 multipart), add one or more
sample batches (sample sheet + tag selection), and submit. A Celery worker builds
`input.tsv`, runs Nextflow on the VM (`-profile docker`), renders the R report, uploads
results to S3, and emails the user. See [docs/architecture.md](docs/architecture.md).

## Development

- Backend: `backend/` — FastAPI, Postgres, Celery/Redis. See `backend/README.md`.
- Frontend: `frontend/` — React + Vite.
- Local stack: `deploy/docker-compose.yml`.
