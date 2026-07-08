"""Smoke test: models create, app imports, register -> login -> me works."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./smoke.db")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401
from app.main import app  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_register_login_me():
    r = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "supersecret1", "organisation": "Lab"},
    )
    assert r.status_code == 201, r.text
    tok = r.json()["access_token"]
    assert r.json()["user"]["role"] == "user"

    # duplicate registration rejected
    r2 = client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "supersecret1"}
    )
    assert r2.status_code == 409

    # login via OAuth2 form
    r3 = client.post(
        "/api/auth/login", data={"username": "a@b.com", "password": "supersecret1"}
    )
    assert r3.status_code == 200, r3.text

    # /me with bearer token
    r4 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r4.status_code == 200
    assert r4.json()["email"] == "a@b.com"

    # /me without token rejected
    assert client.get("/api/auth/me").status_code == 401
