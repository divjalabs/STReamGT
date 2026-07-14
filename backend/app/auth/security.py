"""Password hashing and JWT creation/verification."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def _prep(password: str) -> bytes:
    """Pre-hash to a fixed 44-byte token so bcrypt's 72-byte cap never truncates."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prep(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prep(plain), hashed.encode("ascii"))
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def create_reset_token(user_id: int) -> str:
    """A short-lived, single-purpose JWT for password resets (no DB row needed)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "purpose": "pwreset",
        "iat": now,
        "exp": now + timedelta(minutes=settings.reset_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_reset_token(token: str) -> int | None:
    """Return the user id from a valid, unexpired pwreset token, else None."""
    payload = decode_access_token(token)
    if not payload or payload.get("purpose") != "pwreset":
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
