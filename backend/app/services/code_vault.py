"""Reversible storage for a kit's claim code, so the sticker sheet can be printed twice.

The code's keyed HMAC (services/claim_codes.py) stays the thing redeem looks up — that is a
one-way fingerprint and cannot be read back. This module keeps a second, *sealed* copy alongside
it, which an admin can unseal to reprint a sheet that was lost or never downloaded.

Encrypted rather than stored in plain text, because the database does not stay in the database:
it is dumped to s3://<bucket>/backups/db/ every Sunday and kept for 180 days (infra/backup.tf),
and scripts/backup.sh syncs those dumps to a laptop. A claim code is a bearer token — whoever
reads an unclaimed one can take that kit. The key below lives in Parameter Store, in neither the
dumps nor the database, so a leak of either yields nothing usable.

Fernet, not a hand-rolled construction: it carries its own nonce and authentication tag, so there
is no nonce to accidentally reuse and a tampered blob fails loudly instead of decrypting to
rubbish.
"""
from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

# Fernet wants 32 url-safe base64 bytes; the configured secret is an arbitrary string.
_INFO = b"|claim-code-sealing"


def _fernet() -> Fernet:
    """Built per call, deliberately: the settings object is mutable and tests rotate keys on it.

    Keyed on the same secret as claim_codes._key() — read that docstring for why it is not
    secret_key. Derived through a hash with a distinct suffix so the sealing key and the HMAC key
    are different values, and neither can be used to attack the other.
    """
    secret = (settings.claim_code_key or settings.secret_key).encode()
    return Fernet(urlsafe_b64encode(sha256(secret + _INFO).digest()))


def seal(plaintext: str) -> str:
    """The blob to store next to the HMAC."""
    return _fernet().encrypt(plaintext.encode()).decode()


def unseal(blob: str | None) -> str | None:
    """The original code, or None if there is nothing readable here.

    None rather than an exception for a blob that will not open — a row sealed under a retired
    key, or a truncated value — so that one unreadable kit cannot fail a whole sticker sheet.
    """
    if not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError):
        return None
