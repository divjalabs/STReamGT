"""Which secret signs what, and refusing to run on the one that is public.

Two separate problems this guards:
  * `secret_key` used to sign kit claim codes as well as logins. Rotating it — the first thing
    you would do if it leaked — would have destroyed every unredeemed code on kits already posted
    to labs, because only the hash is stored.
  * its default is a placeholder committed to a public repository, and nothing stopped the app
    running on it.
"""
from __future__ import annotations

import pytest

from app.config import Settings, _assert_usable_in_production
from app.services import claim_codes


REAL_KEY = "a-real-looking-secret-value"


def _settings(**over) -> Settings:
    base = {"environment": "production", "secret_key": REAL_KEY, "claim_code_key": "codes-key"}
    return Settings(**{**base, **over})


# --- the point of the split ------------------------------------------------------------

def test_a_claim_code_survives_a_login_key_rotation(monkeypatch):
    """The regression this change exists to prevent."""
    monkeypatch.setattr(claim_codes.settings, "secret_key", "login-key-v1")
    monkeypatch.setattr(claim_codes.settings, "claim_code_key", "codes-key")

    code = claim_codes.generate_code()
    stored = claim_codes.hmac_code(code)

    monkeypatch.setattr(claim_codes.settings, "secret_key", "login-key-v2")  # leaked, rotated

    assert claim_codes.hmac_code(code) == stored, (
        "rotating the login key must not invalidate codes already printed on kits"
    )


def test_claim_codes_do_not_use_the_login_key(monkeypatch):
    monkeypatch.setattr(claim_codes.settings, "secret_key", "login-key")
    monkeypatch.setattr(claim_codes.settings, "claim_code_key", "codes-key")
    with_own_key = claim_codes.hmac_code("ABCD-EFGH-JKMN-PQRS")

    monkeypatch.setattr(claim_codes.settings, "claim_code_key", None)
    assert claim_codes.hmac_code("ABCD-EFGH-JKMN-PQRS") != with_own_key, (
        "falling back to the login key should produce a different hash — that is the coupling"
    )


def test_the_fallback_keeps_local_development_working(monkeypatch):
    """No claim-code key configured: still usable, just keyed on secret_key."""
    monkeypatch.setattr(claim_codes.settings, "secret_key", "dev-secret")
    monkeypatch.setattr(claim_codes.settings, "claim_code_key", None)
    code = claim_codes.generate_code()
    assert claim_codes.hmac_code(code) == claim_codes.hmac_code(code.lower().replace("-", " "))


# --- refusing to run on the public placeholder -----------------------------------------

def test_production_refuses_the_placeholder_key():
    with pytest.raises(RuntimeError) as err:
        _assert_usable_in_production(_settings(secret_key="change-me-in-prod"))
    assert "SECRET_KEY" in str(err.value)
    assert "placeholder" in str(err.value)


def test_production_refuses_a_missing_claim_code_key():
    with pytest.raises(RuntimeError, match="CLAIM_CODE_KEY"):
        _assert_usable_in_production(_settings(claim_code_key=None))


def test_production_starts_when_both_are_set():
    _assert_usable_in_production(_settings())    # must not raise


def test_development_is_left_alone():
    """The placeholder is the whole point of the default: `git clone` and run."""
    _assert_usable_in_production(
        _settings(environment="development", secret_key="change-me-in-prod", claim_code_key=None)
    )
