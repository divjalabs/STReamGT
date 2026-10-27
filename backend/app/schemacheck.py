"""Compare a live database against the SQLAlchemy models. Read-only — issues no DDL.

    DATABASE_URL="postgresql+psycopg://…" python -m app.schemacheck

Prints what the models expect but the database lacks (MISSING), and what the database has that no
model declares (EXTRA — usually harmless leftovers). Exits 1 when anything is MISSING, so it can
gate a deploy.

Use it before and after a migration, and before `alembic stamp`: stamping a database that is NOT
actually at that revision is how schema drift becomes invisible.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  — importing registers every table on Base.metadata


def make_engine():
    """Resolve the URL when called, so `DATABASE_URL=… python -m app.schemacheck` works and the
    tests can point this at a throwaway database."""
    return create_engine(os.environ.get("DATABASE_URL") or settings.resolved_database_url)


def diff(engine=None) -> tuple[list[str], list[str]]:
    insp = inspect(engine or make_engine())
    db_tables = set(insp.get_table_names())
    missing: list[str] = []
    extra: list[str] = []

    for name, table in sorted(Base.metadata.tables.items()):
        if name not in db_tables:
            missing.append(f"table {name}")
            continue
        db_cols = {c["name"]: c for c in insp.get_columns(name)}
        for col in table.columns:
            if col.name not in db_cols:
                missing.append(f"column {name}.{col.name} ({col.type})")
        for col_name in db_cols:
            if col_name not in table.columns:
                extra.append(f"column {name}.{col_name}")

    for name in sorted(db_tables - set(Base.metadata.tables) - {"alembic_version"}):
        extra.append(f"table {name}")

    return missing, extra


def main() -> None:
    url = make_engine().url
    print(f"database: {url.host or url.database}/{url.database}")
    missing, extra = diff()

    if missing:
        print(f"\nMISSING from the database ({len(missing)}) — the app would fail on these:")
        for m in missing:
            print(f"  - {m}")
    if extra:
        print(f"\nEXTRA in the database ({len(extra)}) — no model declares these:")
        for e in extra:
            print(f"  - {e}")
    if not missing and not extra:
        print("\nNo differences: the database matches the models.")

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
