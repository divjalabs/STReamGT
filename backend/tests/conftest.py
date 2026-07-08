"""Shared test fixtures: a fresh sqlite DB and TestClient with helper auth + seeded catalog."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import Base, engine, SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models import User, UserRole, PrimerPanel  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.seed_catalog import seed_catalog  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield TestClient(app)


@pytest.fixture()
def catalog(client):
    """Seed the primer panels + tag layout (no S3 upload)."""
    seed_catalog(upload_to_s3=False)


def _make_user(email: str, password: str, role: UserRole) -> None:
    with SessionLocal() as db:
        db.add(User(email=email, password_hash=hash_password(password), role=role))
        db.commit()


def user_id(email: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == email))


def panel_id(code: str = "UA_primers") -> int:
    with SessionLocal() as db:
        return db.scalar(select(PrimerPanel.id).where(PrimerPanel.code == code))


@pytest.fixture()
def admin_token(client):
    _make_user("admin@x.com", "adminpass123", UserRole.admin)
    r = client.post("/api/auth/login", data={"username": "admin@x.com", "password": "adminpass123"})
    return r.json()["access_token"]


@pytest.fixture()
def user_token(client):
    r = client.post(
        "/api/auth/register", json={"email": "user@x.com", "password": "userpass123"}
    )
    return r.json()["access_token"]


def register(client, email: str, password: str = "clientpass123") -> str:
    """Register a client and return their token."""
    return client.post(
        "/api/auth/register", json={"email": email, "password": password}
    ).json()["access_token"]


def bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}
