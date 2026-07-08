"""Kit catalog: admin registers kits from panels + tag columns; per-user access; status."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    User, Kit, TagColumn, Control, PrimerPanel, TagLayout, KitStatus, kit_access,
)
from app.auth.deps import get_current_user, require_admin
from app.schemas.kit import KitCreate, KitUpdate, KitOut, KitSummary
from app.schemas.panel import TagLayoutOut

router = APIRouter(prefix="/kits", tags=["kits"])


def _pp_ordinal(name: str) -> int:
    m = re.findall(r"\d+", name)
    return int(m[0]) if m else 0


def _global_tag_layout(db: Session) -> TagLayout:
    layout = db.scalar(select(TagLayout).order_by(TagLayout.id))
    if layout is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No tag layout configured (seed it first)")
    return layout


def _can_access(kit: Kit, user: User) -> bool:
    return user.is_admin or any(u.id == user.id for u in kit.users)


# ---------- tag layout (for the admin kit form) ----------

@router.get("/tag-layout", response_model=TagLayoutOut)
def get_tag_layout(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _global_tag_layout(db)


# ---------- list / get (access-filtered) ----------

@router.get("", response_model=list[KitSummary])
def list_kits(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """Admins see all kits; non-admins see only kits granted to them."""
    stmt = select(Kit).order_by(Kit.kit_code)
    if not current.is_admin:
        stmt = stmt.join(kit_access, kit_access.c.kit_id == Kit.id).where(
            kit_access.c.user_id == current.id
        )
    return db.scalars(stmt).all()


@router.get("/{kit_id}", response_model=KitOut)
def get_kit(kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    if not _can_access(kit, current):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
    return kit


# ---------- create (admin, from a panel) ----------

@router.post("", response_model=KitOut, status_code=status.HTTP_201_CREATED)
def create_kit(payload: KitCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.scalar(select(Kit).where(Kit.kit_code == payload.kit_code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "kit_code already exists")

    panel = db.get(PrimerPanel, payload.panel_id)
    if panel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Primer panel not found")

    layout = _global_tag_layout(db)
    unknown = set(payload.selected_tags) - set(layout.column_names)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"tag columns not in the layout: {sorted(unknown)}",
        )

    assigned = db.scalars(select(User).where(User.id.in_(payload.assigned_user_ids))).all()

    kit = Kit(
        kit_code=payload.kit_code,
        panel_id=panel.id,
        species=panel.species_common,          # denormalized for the submit page
        description=payload.description,
        status=payload.status,
        primers_csv_key=panel.primers_csv_key,  # denormalized so the worker is unchanged
        tags_csv_key=layout.tags_csv_key,
        created_by=admin.id,
        tag_columns=[
            TagColumn(name=t, ordinal=_pp_ordinal(t)) for t in payload.selected_tags
        ],
        controls=[Control(**c.model_dump()) for c in payload.controls],
        users=list(assigned),
    )
    db.add(kit)
    db.commit()
    db.refresh(kit)
    return kit


# ---------- update status / access ----------

@router.patch("/{kit_id}", response_model=KitOut)
def update_kit(
    kit_id: int, payload: KitUpdate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")

    if current.is_admin:
        if payload.status is not None:
            kit.status = payload.status
        if payload.description is not None:
            kit.description = payload.description
        if payload.assigned_user_ids is not None:
            kit.users = list(
                db.scalars(select(User).where(User.id.in_(payload.assigned_user_ids))).all()
            )
    else:
        # A client with access may only confirm receipt.
        if not _can_access(kit, current):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
        if payload.status is not None and payload.status != KitStatus.received:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You may only set status to 'received'")
        if payload.status is not None:
            kit.status = KitStatus.received
    db.commit()
    db.refresh(kit)
    return kit


@router.delete("/{kit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kit(kit_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    db.delete(kit)
    db.commit()
