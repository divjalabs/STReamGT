"""Which secret signs what, and making sure each one reaches the processes that need it.

Three separate problems this guards:
  * `secret_key` used to sign kit claim codes as well as logins. Rotating it — the first thing
    you would do if it leaked — would have destroyed every unredeemed code on kits already posted
    to labs, because only the hash is stored.
  * its default is a placeholder committed to a public repository, and nothing stopped the app
    running on it.
  * splitting the keys added a setting the app refuses to start without, and it was delivered to
    the Lambda but not to ECS tasks. The API was fine; the weekly backup and every genotyping run
    died at import for three days before the backup alarm said so.
"""
from __future__ import annotations

import pytest

from app.config import Settings, _assert_usable_in_production
from app.services import claim_codes, code_vault


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


# --- the sealed copy a sticker sheet is reprinted from ---------------------------------

def test_a_sealed_code_comes_back_out(monkeypatch):
    monkeypatch.setattr(code_vault.settings, "claim_code_key", "codes-key")
    code = claim_codes.generate_code()
    assert code_vault.unseal(code_vault.seal(code)) == code


def test_the_sealed_blob_does_not_contain_the_code(monkeypatch):
    """Otherwise a database dump would hand the codes over anyway, which is the whole point."""
    monkeypatch.setattr(code_vault.settings, "claim_code_key", "codes-key")
    code = claim_codes.generate_code()
    blob = code_vault.seal(code)
    assert code not in blob
    assert claim_codes._normalize(code) not in blob


def test_a_blob_sealed_under_another_key_will_not_open(monkeypatch):
    """A rotated claim-code key makes old codes unreadable — the same cost as the HMAC's."""
    monkeypatch.setattr(code_vault.settings, "claim_code_key", "codes-key-v1")
    blob = code_vault.seal("K7QF-3M9P-XR2A-WD6H")

    monkeypatch.setattr(code_vault.settings, "claim_code_key", "codes-key-v2")
    assert code_vault.unseal(blob) is None, "one unreadable row must not fail a whole sheet"


def test_nothing_sealed_means_nothing_to_unseal():
    assert code_vault.unseal(None) is None
    assert code_vault.unseal("") is None
    assert code_vault.unseal("not-a-token") is None


def test_sealing_follows_the_claim_code_key_not_the_login_key(monkeypatch):
    """Same guarantee as the HMAC's: rotating the login key leaves kits in the post alone."""
    monkeypatch.setattr(code_vault.settings, "secret_key", "login-key-v1")
    monkeypatch.setattr(code_vault.settings, "claim_code_key", "codes-key")
    blob = code_vault.seal("K7QF-3M9P-XR2A-WD6H")

    monkeypatch.setattr(code_vault.settings, "secret_key", "login-key-v2")  # leaked, rotated
    assert code_vault.unseal(blob) == "K7QF-3M9P-XR2A-WD6H"


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


# --- the secret has to reach every process, not just the API ---------------------------
# The claim-code key was created in Parameter Store and picked up by the Lambda, which reads the
# whole path. ECS task definitions name their secrets one at a time, and nobody added it there,
# so for three days the weekly backup and every genotyping run died at import on the guard above.

def test_every_required_secret_is_delivered_to_ecs_tasks():
    import re
    from pathlib import Path

    from app.config import REQUIRED_IN_PRODUCTION

    main_tf = Path(__file__).resolve().parents[2] / "infra" / "main.tf"
    if not main_tf.exists():
        pytest.skip("infra/ is not part of this checkout")

    m = re.search(r"secret_param_names\s*=\s*\[([^\]]*)\]", main_tf.read_text())
    assert m, "could not find local.secret_param_names in infra/main.tf"
    delivered = set(re.findall(r'"([^"]+)"', m.group(1)))

    missing = [name for name in REQUIRED_IN_PRODUCTION if name not in delivered]
    assert not missing, (
        f"{missing} must start the app in production but no ECS task definition injects them. "
        "Add them to local.secret_param_names in infra/main.tf and apply, or the next ECS task "
        "to run will fail at import."
    )
