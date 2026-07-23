"""Kit claim codes: generate a shippable code, store only its keyed HMAC.

The plaintext code is shown to the admin once at kit creation and never persisted. Redeem looks the
kit up by HMAC (deterministic, so equality lookup works) — a DB leak can't forge codes without the
server secret. Codes are ~80 bits of entropy, formatted XXXX-XXXX-XXXX-XXXX.
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


def hmac_code(code: str) -> str:
    """Keyed HMAC of a (normalized) code — what we store and look up by."""
    return hmac.new(
        settings.secret_key.encode(), _normalize(code).encode(), sha256
    ).hexdigest()


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
    db.flush()
    return kit


def assign_new_code(kit: Kit) -> str:
    """Generate a fresh code, store its hmac on the kit, and return the plaintext (show once)."""
    code = generate_code()
    kit.claim_code_hmac = hmac_code(code)
    return code
