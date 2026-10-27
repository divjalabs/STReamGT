# STReamGT backend

FastAPI + Celery + SQLAlchemy. Serves the web API and runs the Nextflow pipeline
asynchronously on a worker.

## Layout

```
app/
├── main.py            FastAPI app (health + routers)
├── config.py          Settings from env / .env
├── db.py              SQLAlchemy engine, session, Base
├── models/            User, Kit(+Primer,TagColumn,Control), Job(+SampleBatch,ResultFile)
├── schemas/           Pydantic request/response models
├── auth/              password hashing, JWT, get_current_user / require_admin
├── api/               routers: auth (kits, jobs added in later milestones)
├── services/          storage (S3), samplesheet (input.tsv builder), notify (email)
├── worker/            celery_app + tasks.run_pipeline
└── bootstrap.py       dev-only create_all + first admin
alembic/               migrations (production schema management)
```

## Local dev (without Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Point at a local DB (sqlite is fine for a quick smoke test):
export DATABASE_URL="sqlite+pysqlite:///./dev.db"

# Create tables + an admin:
python -m app.bootstrap --admin-email admin@example.com --admin-password changeme123

# Run the API:
uvicorn app.main:app --reload
# -> http://localhost:8000/docs
```

## Migrations (Postgres)

```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

## Worker

```bash
celery -A app.worker.celery_app.celery_app worker --loglevel=info
```
