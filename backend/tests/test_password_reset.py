"""Password-reset flow: forgot-password emails a token, reset-password consumes it."""
from urllib.parse import urlparse, parse_qs

from tests.conftest import register


def _capture_reset(monkeypatch) -> dict:
    """Intercept the reset email and record the recipient + link instead of sending."""
    captured = {}
    monkeypatch.setattr(
        "app.api.auth.notify.send_password_reset",
        lambda to, reset_url: captured.update(to=to, url=reset_url),
    )
    return captured


def test_forgot_password_says_when_there_is_no_account(client, monkeypatch):
    """Deliberately not the vague answer: a typo must not look like a successful send."""
    captured = _capture_reset(monkeypatch)
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@x.com"})
    assert r.status_code == 404
    assert "No account" in r.json()["detail"]
    assert captured == {}                # and nothing was emailed


def test_forgot_password_tells_a_disabled_account_to_ask_an_admin(client, monkeypatch):
    """The one case the person cannot fix themselves, so silence would send them in circles."""
    from app.db import SessionLocal
    from app.models import User
    from sqlalchemy import select

    captured = _capture_reset(monkeypatch)
    register(client, "disabled@x.com", "oldpassword1")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "disabled@x.com"))
        user.is_active = False
        db.commit()

    r = client.post("/api/auth/forgot-password", json={"email": "disabled@x.com"})
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]
    assert captured == {}


def test_password_reset_flow(client, monkeypatch):
    register(client, "reset@x.com", "oldpassword1")
    captured = _capture_reset(monkeypatch)

    r = client.post("/api/auth/forgot-password", json={"email": "reset@x.com"})
    assert r.status_code == 204
    token = parse_qs(urlparse(captured["url"]).query)["token"][0]

    r = client.post("/api/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert r.status_code == 204

    # old password no longer works; new one does
    assert client.post("/api/auth/login", data={"username": "reset@x.com", "password": "oldpassword1"}).status_code == 401
    assert client.post("/api/auth/login", data={"username": "reset@x.com", "password": "newpassword1"}).status_code == 200


def test_reset_password_rejects_bad_token(client):
    r = client.post("/api/auth/reset-password", json={"token": "garbage", "new_password": "whatever12"})
    assert r.status_code == 400


def test_reset_password_rejects_plain_access_token(client):
    """A normal login token must not be accepted as a password-reset token."""
    tok = register(client, "victim@x.com", "origpass123")
    r = client.post("/api/auth/reset-password", json={"token": tok, "new_password": "hacked12345"})
    assert r.status_code == 400
    # the original password still works
    assert client.post("/api/auth/login", data={"username": "victim@x.com", "password": "origpass123"}).status_code == 200
