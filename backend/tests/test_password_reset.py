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


def test_forgot_password_unknown_email_is_silent_204(client, monkeypatch):
    captured = _capture_reset(monkeypatch)
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@x.com"})
    assert r.status_code == 204          # never reveals whether the email exists
    assert captured == {}                # and no email is sent


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
