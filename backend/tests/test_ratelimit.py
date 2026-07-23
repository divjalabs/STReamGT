"""In-memory rate limiting (disabled suite-wide; enabled just for this test)."""
from app.config import settings
from app.services import ratelimit


def test_login_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.reset()
    max_calls = ratelimit.LIMITS["login"][0]
    codes = [
        client.post("/api/auth/login", data={"username": "x@y.com", "password": "nope"}).status_code
        for _ in range(max_calls + 3)
    ]
    # first `max_calls` attempts are allowed through (401 bad creds), then throttled (429)
    assert codes[:max_calls] == [401] * max_calls
    assert 429 in codes[max_calls:]
    ratelimit.reset()


def test_disabled_by_default(client, monkeypatch):
    ratelimit.reset()
    # suite default is off → no throttling even past the limit
    codes = [
        client.post("/api/auth/login", data={"username": "x@y.com", "password": "nope"}).status_code
        for _ in range(ratelimit.LIMITS["login"][0] + 3)
    ]
    assert 429 not in codes
