"""Dev bootstrap: create tables (no Alembic) and an initial admin user.

For production use Alembic migrations instead of create_all.

Usage:
    python -m app.bootstrap --admin-email admin@example.com --admin-password secret123
    python -m app.bootstrap --reset --seed --admin-email ... --admin-password ...   # fresh DB
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import Base, engine, SessionLocal
import app.models  # noqa: F401  registers tables
from app.models import User, UserRole
from app.auth.security import hash_password
from app.seed_catalog import seed_catalog


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def reset_tables() -> None:
    """DESTRUCTIVE: drop everything and recreate. On Postgres, drop the whole schema with CASCADE
    so a *previous, incompatible* schema (stale FKs metadata.drop_all can't order) is wiped clean."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            conn.exec_driver_sql("CREATE SCHEMA public")
    else:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def create_admin(email: str, password: str, organisation: str | None = None) -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"admin {email} already exists")
            return
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                organisation=organisation,
                role=UserRole.admin,
            )
        )
        db.commit()
        print(f"created admin {email}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--admin-email")
    p.add_argument("--admin-password")
    p.add_argument("--organisation", default=None)
    p.add_argument("--reset", action="store_true", help="DROP + recreate all tables (destructive)")
    p.add_argument("--seed", action="store_true", help="seed primer panels + tag layout")
    p.add_argument("--no-s3", action="store_true", help="seed without uploading CSVs to S3 (local)")
    args = p.parse_args()

    if args.reset:
        reset_tables()
        print("tables reset (dropped + recreated)")
    else:
        create_tables()
        print("tables created")
    if args.admin_email and args.admin_password:
        create_admin(args.admin_email, args.admin_password, args.organisation)
    if args.seed:
        seed_catalog(upload_to_s3=not args.no_s3)


if __name__ == "__main__":
    main()
