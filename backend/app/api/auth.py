"""Authentication routes: register, login, current user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
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
)
from app.services import notify

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
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
    except Exception:  # noqa: BLE001
        pass

    token = create_access_token(str(user.id), extra={"role": user.role.value})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    # OAuth2PasswordRequestForm uses "username"; we treat it as the email.
    user = db.scalar(select(User).where(User.email == form.username))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    token = create_access_token(str(user.id), extra={"role": user.role.value})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(payload: ForgotPasswordIn, db: Session = Depends(get_db)) -> None:
    """Email a password-reset link. Always 204 — never reveals whether the email exists."""
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is not None and user.is_active:
        token = create_reset_token(user.id)
        reset_url = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={token}"
        try:
            notify.send_password_reset(user.email, reset_url)
        except Exception:  # noqa: BLE001 — never leak send failures or block the flow
            pass


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
