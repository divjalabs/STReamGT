"""Idempotent additive schema upgrade for the create_all-managed production DB.

The live Aurora schema is managed by `app.bootstrap` (create_all), not Alembic, so
`alembic upgrade` can't be applied cleanly. This script applies the *additive* changes from
migrations 0005 (kits.updated_at) and 0006 (controls) using IF NOT EXISTS guards, so it is safe
to run repeatedly and regardless of Alembic state.

    python -m app.dbupgrade
"""
from __future__ import annotations

from sqlalchemy import text

from app.db import engine

# Enum values must be added in autocommit (not inside a transaction block).
ENUM_VALUES = ["sequencing", "pcr", "extraction"]

DDL = [
    # 0005 — kits.updated_at
    "ALTER TABLE kits ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()",
    # 0006 — controls position/name (+ name_pattern optional)
    "ALTER TABLE controls ADD COLUMN IF NOT EXISTS position varchar(8)",
    "ALTER TABLE controls ADD COLUMN IF NOT EXISTS name varchar(255)",
    "ALTER TABLE controls ALTER COLUMN name_pattern DROP NOT NULL",
    # 0006 — sample control flags
    "ALTER TABLE samples ADD COLUMN IF NOT EXISTS is_control boolean NOT NULL DEFAULT false",
    "ALTER TABLE samples ADD COLUMN IF NOT EXISTS control_type control_kind",
    # 0006 — control_templates
    """CREATE TABLE IF NOT EXISTS control_templates (
        id serial PRIMARY KEY,
        name varchar(128) NOT NULL UNIQUE,
        created_by integer REFERENCES users(id),
        created_at timestamptz NOT NULL DEFAULT now(),
        positions json NOT NULL DEFAULT '[]'::json
    )""",
]


def main() -> None:
    is_pg = engine.dialect.name == "postgresql"
    if is_pg:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for v in ENUM_VALUES:
                conn.execute(text(f"ALTER TYPE control_kind ADD VALUE IF NOT EXISTS '{v}'"))
                print(f"enum control_kind += {v}")
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
            print("ok:", stmt.split("\n")[0].strip())
    print("dbupgrade complete")


if __name__ == "__main__":
    main()
