"""Alembic migration environment, wired to the app's Base metadata and settings."""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base
import app.models  # noqa: F401  (import registers all models on Base.metadata)

config = context.config
# Read DATABASE_URL here rather than trusting the app's cached settings object: migrations are
# routinely pointed at a different database than the process was configured with
# (`DATABASE_URL=… alembic upgrade head`), and the cached singleton would silently ignore it.
config.set_main_option(
    "sqlalchemy.url", os.environ.get("DATABASE_URL") or settings.resolved_database_url
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.resolved_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
