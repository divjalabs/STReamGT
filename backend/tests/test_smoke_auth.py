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


def test_update_profile_and_change_password():
    tok = client.post(
        "/api/auth/register", json={"email": "acct@b.com", "password": "origpass123"}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # self-service organisation update, reflected by /me
    r = client.patch("/api/auth/me", json={"organisation": "NewOrg"}, headers=h)
    assert r.status_code == 200 and r.json()["organisation"] == "NewOrg"
    assert client.get("/api/auth/me", headers=h).json()["organisation"] == "NewOrg"

    # wrong current password rejected
    assert client.post("/api/auth/change-password",
                       json={"current_password": "wrong", "new_password": "brandnew123"},
                       headers=h).status_code == 400
    # correct current password -> 204
    assert client.post("/api/auth/change-password",
                       json={"current_password": "origpass123", "new_password": "brandnew123"},
                       headers=h).status_code == 204
    # old password no longer works; the new one does
    assert client.post("/api/auth/login",
                       data={"username": "acct@b.com", "password": "origpass123"}).status_code == 401
    assert client.post("/api/auth/login",
                       data={"username": "acct@b.com", "password": "brandnew123"}).status_code == 200


# --- what the email field actually accepts -------------------------------------------------
# "You can write anything in the email field" was a reporting problem, not a validation one:
# the frontend rendered the 422 body as raw JSON, so the rejection looked like a crash. These
# pin the two halves the UI depends on — that bad addresses are refused, and the shape of the
# refusal that client.js turns into a sentence.

def test_a_malformed_email_is_refused_in_the_shape_the_ui_parses():
    r = client.post("/api/auth/register", json={"email": "abc@def", "password": "password123"})
    assert r.status_code == 422
    err = r.json()["detail"][0]
    assert err["loc"][-1] == "email", "client.js names the field from the last element of loc"
    assert "valid email" in err["msg"]


def test_capitals_cannot_create_a_second_account():
    """EmailStr lowercases the domain but not the local part, so without normalising these would
    be two accounts — and the second one would hold none of the first one's kits."""
    first = client.post(
        "/api/auth/register", json={"email": "Mixed.Case@Lab.ORG", "password": "password123"}
    )
    assert first.status_code == 201
    assert first.json()["user"]["email"] == "mixed.case@lab.org"

    again = client.post(
        "/api/auth/register", json={"email": "mixed.case@lab.org", "password": "password123"}
    )
    assert again.status_code == 409

    # and the address logs in however it is typed
    for typed in ("Mixed.Case@Lab.ORG", "mixed.case@lab.org", "MIXED.CASE@LAB.ORG"):
        r = client.post("/api/auth/login", data={"username": typed, "password": "password123"})
        assert r.status_code == 200, typed
