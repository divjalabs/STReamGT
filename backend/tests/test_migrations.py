"""The migrations must build exactly the schema the models expect.

Three columns once existed only in a hand-written upgrade script, so a database built purely from
Alembic was missing them and nothing noticed: the rest of the suite runs on SQLite via
`create_all`, which never touches a migration.

Needs a real Postgres, because the schema uses native enums, timestamptz and ON DELETE CASCADE.
Point TEST_PG_URL at a throwaway database — the test wipes it:

    docker run -d --rm --name pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=streamgt \
        -p 55432:5432 postgres:16
    TEST_PG_URL="postgresql+psycopg://postgres:test@localhost:55432/streamgt" \
        PYTHONPATH=. .venv/bin/pytest tests/test_migrations.py
"""
from __future__ import annotations

import os

import pytest

TEST_PG_URL = os.environ.get("TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL,
    reason="set TEST_PG_URL to a throwaway Postgres to run the migration tests (see this file's docstring)",
)


@pytest.fixture()
def pg_env(monkeypatch):
    """Point alembic/env.py and schemacheck at the throwaway Postgres (both read DATABASE_URL
    when called, so no module reloading is needed)."""
    monkeypatch.setenv("DATABASE_URL", TEST_PG_URL)
    yield


def _reset_schema():
    """Drop everything, including enum types — `downgrade base` drops tables but leaves the
    native enums behind, so a straight re-upgrade would collide with them."""
    from sqlalchemy import text
    from app import schemacheck

    engine = schemacheck.make_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _alembic_config():
    from alembic.config import Config
    from pathlib import Path

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    return cfg


def test_upgrade_head_matches_the_models(pg_env):
    """`alembic upgrade head` on an empty database must leave nothing missing."""
    from alembic import command

    _reset_schema()
    command.upgrade(_alembic_config(), "head")

    from app import schemacheck

    missing, extra = schemacheck.diff()

    assert not missing, (
        "the migrations do not create everything the models declare:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd a migration for each item above (see alembic/versions/0009_* for the pattern)."
    )
    assert not extra, "the database has objects no model declares:\n  " + "\n  ".join(extra)


def test_downgrade_to_base_is_clean(pg_env):
    """Every migration must be reversible, so a bad upgrade can be backed out."""
    from alembic import command
    from sqlalchemy import inspect

    _reset_schema()
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    from app import schemacheck

    tables = set(inspect(schemacheck.make_engine()).get_table_names()) - {"alembic_version"}
    assert not tables, f"downgrade left tables behind: {sorted(tables)}"
