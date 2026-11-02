"""User administration (admin): list users, promote to admin, (de)activate, delete."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    ConsensusEditLog, ConsensusGenotype, ControlTemplate, Job, Kit, KitReads, MatchingRun,
    Project, User, UserRole,
)
from app.auth.deps import require_admin
from app.schemas.user import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _is_last_admin(db: Session, user: User) -> bool:
    """True if removing this account's admin rights would leave nobody able to administer.

    Nothing stopped this before: the Users page hides the buttons on your own row, but a direct
    API call could demote or deactivate the only admin, and there is no way back in through the
    UI after that.
    """
    if not user.is_admin:
        return False
    others = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.admin, User.id != user.id, User.is_active)
    )
    return not others


# What points at a user, and the words to describe it when we refuse to delete them. Order is
# roughly "most alarming first", since the message lists them in this order.
#
# kit_access and project_access are deliberately absent: those two are the only FKs to users with
# ON DELETE CASCADE, because an access grant with nothing behind it is exactly what should
# disappear along with the account. The kit or project itself is untouched.
_DEPENDENTS: list[tuple[str, str, object, object]] = [
    ("analysis", "analyses", Job, Job.user_id),
    ("project", "projects", Project, Project.owner_user_id),
    ("claimed kit", "claimed kits", Kit, Kit.claimed_by),
    ("registered kit", "registered kits", Kit, Kit.created_by),
    ("uploaded read set", "uploaded read sets", KitReads, KitReads.uploaded_by),
    ("control template", "control templates", ControlTemplate, ControlTemplate.created_by),
    ("matching run", "matching runs", MatchingRun, MatchingRun.triggered_by),
    ("edited genotype", "edited genotypes", ConsensusGenotype, ConsensusGenotype.edited_by),
    ("genotype edit", "genotype edits", ConsensusEditLog, ConsensusEditLog.user_id),
]


def _what_depends_on(db: Session, user: User) -> list[str]:
    """Human-readable counts of everything still pointing at this account, e.g. ["3 analyses"]."""
    found = []
    for singular, plural, model, column in _DEPENDENTS:
        n = db.scalar(select(func.count()).select_from(model).where(column == user.id))
        if n:
            found.append(f"{n} {singular if n == 1 else plural}")
    return found


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, payload: UserUpdate,
    db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    demoting = payload.role is not None and payload.role != user.role
    deactivating = payload.is_active is False and user.is_active

    if user.id == admin.id and demoting:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own role")
    if user.id == admin.id and deactivating:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account")
    if (demoting or deactivating) and _is_last_admin(db, user):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the only active admin. Promote another account first, or there will be "
            "nobody left who can.",
        )

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    """Remove an account that holds nothing. Refuses, with the reason, if anything points at it.

    Deliberately all-or-nothing rather than nulling the columns that allow it: a kit's
    `claimed_by` in particular must never be cleared, because the sealed claim code is destroyed
    when the kit is claimed (services/claim_codes.py), so a kit that looked unclaimed again could
    be neither claimed nor reprinted. Deactivating is the tool for an account with history — it
    blocks access on the next request and keeps every record attached to a real person.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    if _is_last_admin(db, user):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the only active admin and cannot be deleted. Promote another account first.",
        )

    blockers = _what_depends_on(db, user)
    if blockers:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot delete {user.email}: it has {', '.join(blockers)}. Deactivate the account "
            "instead — that blocks access immediately and keeps the records intact.",
        )

    try:
        db.delete(user)
        db.commit()
    except IntegrityError:
        # Something started referencing the account between the check above and the commit. Also
        # the backstop if a future `ondelete` change ever makes this reachable: the database
        # refuses rather than cascading, and the caller is told, instead of getting a 500.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot delete {user.email}: something now depends on this account. "
            "Deactivate it instead.",
        )
