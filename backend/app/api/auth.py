"""Authentication routes: register, login, current user."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserRole
from app.auth.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_reset_token,
    verify_reset_token,
)
from app.auth.deps import get_current_user
from app.schemas.user import (
    UserCreate,
    UserOut,
    Token,
    ForgotPasswordIn,
    ResetPasswordIn,
    ProfileUpdate,
    ChangePasswordIn,
)
from app.services import notify

logger = logging.getLogger(__name__)
from app.services import ratelimit

router = APIRouter(prefix="/auth", tags=["auth"])


def _by_email(db: Session, email: str) -> User | None:
    """Find a user by email, ignoring case.

    New addresses are lowercased on the way in (schemas.user.UserCreate), but rows created before
    that are stored as typed — so comparing on lower() is what keeps those accounts able to log in
    and reset their password. It also means nobody can register a second account that differs from
    an existing one only by capitals.
    """
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ratelimit.limit("register"))])
def register(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    if _by_email(db, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        organisation=payload.organisation,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Best-effort: notify admins of the new registration (never block signup on email).
    try:
        admin_emails = list(
            db.scalars(select(User.email).where(User.role == UserRole.admin))
        )
        notify.send_new_user_registered(admin_emails, user.email, user.organisation)
    except Exception:  # noqa: BLE001 — never block signup, but leave a trace in the logs
        logger.exception("could not email admins about the new registration (%s)", user.email)

    token = create_access_token(str(user.id), extra={"role": user.role.value})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=Token, dependencies=[Depends(ratelimit.limit("login"))])
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    # OAuth2PasswordRequestForm uses "username"; we treat it as the email.
    user = _by_email(db, form.username)
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    token = create_access_token(str(user.id), extra={"role": user.role.value})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> UserOut:
    """Self-service profile update (organisation only)."""
    current.organisation = payload.organisation
    db.commit()
    db.refresh(current)
    return UserOut.model_validate(current)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(ratelimit.limit("change_password"))])
def change_password(
    payload: ChangePasswordIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> None:
    if not verify_password(payload.current_password, current.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    current.password_hash = hash_password(payload.new_password)
    db.commit()


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(ratelimit.limit("forgot_password"))])
def forgot_password(payload: ForgotPasswordIn, db: Session = Depends(get_db)) -> None:
    """Email a password-reset link, and say so when there is nothing to send it to.

    This used to answer 204 whatever happened, so that nobody could use the form to discover which
    addresses have accounts. That was traded away deliberately: a mistyped address otherwise looks
    exactly like a successful send, and the person waits for a mail that was never addressed to
    them. The clientele is a known handful of labs rather than the public, and the rate limit
    (5/minute per IP, services/ratelimit.py) makes the form a poor way to test a list of addresses.

    Disabled accounts get their own answer: it is the one case the person cannot fix themselves.
    """
    user = _by_email(db, payload.email)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account found for that email.")
    if not user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "That account is disabled — contact your administrator.",
        )

    token = create_reset_token(user.id)
    reset_url = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={token}"
    try:
        notify.send_password_reset(user.email, reset_url)
    except Exception:  # noqa: BLE001 — the send is best-effort, but it must leave a trace: while
        # SES is in sandbox every client address is rejected, and the caller is told "sent".
        logger.exception("password-reset email failed for user id %s", user.id)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)) -> None:
    """Set a new password from a valid reset token."""
    user_id = verify_reset_token(payload.token)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset link")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset link")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
