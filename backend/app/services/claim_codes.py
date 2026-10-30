"""Kit claim codes: generate a shippable code and store its keyed HMAC.

Redeem looks the kit up by HMAC (deterministic, so equality lookup works) — a DB leak can't forge
codes without the server secret. Codes are ~80 bits of entropy, formatted XXXX-XXXX-XXXX-XXXX.

An encrypted copy is kept beside the HMAC (code_vault) so a sticker sheet can be reprinted, and
is destroyed as soon as the kit is claimed.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Kit, User
from app.services import code_vault


class CodeNotFound(Exception):
    """No kit matches the submitted claim code."""


class AlreadyClaimed(Exception):
    """The kit was already claimed by someone else."""

# Crockford-ish base32 without easily confused chars (0/O, 1/I/L).
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_GROUPS = 4
_GROUP_LEN = 4


def generate_code() -> str:
    """A fresh random claim code, e.g. 'K7QF-3M9P-XR2A-WD6H' (~80 bits)."""
    chars = [secrets.choice(_ALPHABET) for _ in range(_GROUPS * _GROUP_LEN)]
    return "-".join("".join(chars[i:i + _GROUP_LEN]) for i in range(0, len(chars), _GROUP_LEN))


def _normalize(code: str) -> str:
    """Uppercase and strip separators/whitespace so entry is forgiving."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _key() -> bytes:
    """The secret these codes are keyed with.

    Deliberately NOT secret_key, which signs logins: the two have opposite rotation costs. A new
    secret_key costs everyone a re-login; a new claim-code key destroys every unredeemed code on
    kits already in the post, since only the hash is stored and it cannot be reversed. Keeping
    them apart means an urgent login-key rotation never touches the kits.

    Falls back to secret_key so local development needs no extra setup; production refuses to
    start without its own value (see config._assert_usable_in_production).
    """
    return (settings.claim_code_key or settings.secret_key).encode()


def hmac_code(code: str) -> str:
    """Keyed HMAC of a (normalized) code — what we store and look up by."""
    return hmac.new(_key(), _normalize(code).encode(), sha256).hexdigest()


def redeem(db: Session, user: User, code: str) -> Kit:
    """Attach the kit matching `code` to `user` (grant access + record the claim).

    Idempotent for the same claimer. Raises CodeNotFound / AlreadyClaimed. Caller commits.
    """
    kit = db.scalar(select(Kit).where(Kit.claim_code_hmac == hmac_code(code)))
    if kit is None:
        raise CodeNotFound()
    if kit.claimed_by is not None and kit.claimed_by != user.id:
        raise AlreadyClaimed()
    if not any(u.id == user.id for u in kit.users):
        kit.users.append(user)
    kit.claimed_by = user.id
    kit.claimed_at = datetime.now(timezone.utc)
    # The code has done its job: claimed_by now blocks anyone else, so there is nothing left worth
    # printing. Dropping the readable copy keeps the stored set down to codes still in the post.
    kit.claim_code_sealed = None
    db.flush()
    return kit


def assign_new_code(kit: Kit) -> str:
    """Generate a fresh code, store it on the kit (hashed and sealed), and return the plaintext.

    Both forms are written together so they can never describe different codes. The sealed copy is
    what reprints a sticker sheet; the HMAC is what redeem looks up.
    """
    code = generate_code()
    kit.claim_code_hmac = hmac_code(code)
    kit.claim_code_sealed = code_vault.seal(code)
    return code


def printable_code(kit: Kit) -> str | None:
    """The kit's claim code if it can still be read back, else None (claimed, or pre-dates sealing)."""
    return code_vault.unseal(kit.claim_code_sealed)
