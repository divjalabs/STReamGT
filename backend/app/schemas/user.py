from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator

from app.models.enums import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    organisation: str | None = None

    @field_validator("email")
    @classmethod
    def _lowercase(cls, v: str) -> str:
        """EmailStr lowercases the domain but keeps the local part, so without this
        Elena@divjalabs.com and elena@divjalabs.com are two different accounts: the duplicate check
        misses, and the lab ends up with a second login holding none of their kits."""
        return v.lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    organisation: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    """Admin-only: promote/demote or (de)activate a user."""

    role: UserRole | None = None
    is_active: bool | None = None


class ProfileUpdate(BaseModel):
    """Self-service: update your own organisation."""

    organisation: str | None = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
