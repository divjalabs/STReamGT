"""Dev bootstrap: create tables (no Alembic) and an initial admin user.

For production use Alembic migrations instead of create_all.

Usage:
    python -m app.bootstrap --admin-email admin@example.com --admin-password secret123
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import Base, engine, SessionLocal
import app.models  # noqa: F401  registers tables
from app.models import User, UserRole
from app.auth.security import hash_password


def create_tables() -> None:
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
    args = p.parse_args()

    create_tables()
    print("tables created")
    if args.admin_email and args.admin_password:
        create_admin(args.admin_email, args.admin_password, args.organisation)


if __name__ == "__main__":
    main()
