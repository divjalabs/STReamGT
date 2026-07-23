"""Reusable plate control layouts an admin can save and apply when registering kits."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, ControlTemplate
from app.auth.deps import require_admin
from app.schemas.kit import ControlTemplateIn, ControlTemplateOut

router = APIRouter(prefix="/control-templates", tags=["control-templates"])


@router.get("", response_model=list[ControlTemplateOut])
def list_templates(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(ControlTemplate).order_by(ControlTemplate.name)).all()


@router.post("", response_model=ControlTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: ControlTemplateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.scalar(select(ControlTemplate).where(ControlTemplate.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A template with that name already exists")
    tpl = ControlTemplate(
        name=payload.name,
        created_by=admin.id,
        positions=[c.model_dump(exclude_none=True) for c in payload.positions],
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    tpl = db.get(ControlTemplate, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    db.delete(tpl)
    db.commit()
