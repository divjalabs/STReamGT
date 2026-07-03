"""Kit catalog: admin-managed kits (primers, tag columns, controls, species)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Kit, Primer, TagColumn, Control, PrimerType
from app.auth.deps import get_current_user, require_admin
from app.schemas.kit import KitCreate, KitOut, KitSummary
from app.services.kit_files import parse_primers_csv, parse_tag_columns

router = APIRouter(prefix="/kits", tags=["kits"])


@router.get("", response_model=list[KitSummary])
def list_kits(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Any authenticated user can list kits (needed for the submit-page picker)."""
    return db.scalars(select(Kit).order_by(Kit.kit_code)).all()


@router.get("/{kit_id}", response_model=KitOut)
def get_kit(kit_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    return kit


@router.post("", response_model=KitOut, status_code=status.HTTP_201_CREATED)
def create_kit(
    payload: KitCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    if db.scalar(select(Kit).where(Kit.kit_code == payload.kit_code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "kit_code already exists")
    kit = Kit(
        kit_code=payload.kit_code,
        species=payload.species,
        description=payload.description,
        primers_csv_key=payload.primers_csv_key,
        tags_csv_key=payload.tags_csv_key,
        created_by=admin.id,
        primers=[Primer(**p.model_dump()) for p in payload.primers],
        tag_columns=[TagColumn(**t.model_dump()) for t in payload.tag_columns],
        controls=[Control(**c.model_dump()) for c in payload.controls],
    )
    db.add(kit)
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


@router.post("/parse", tags=["kits"])
async def parse_kit_files(
    primers_csv: UploadFile = File(...),
    tags_csv: UploadFile = File(...),
    _: User = Depends(require_admin),
):
    """Preview: parse uploaded primers + tags CSVs into catalog structure.

    Lets the admin UI pre-fill a KitCreate form from the real files before saving.
    """
    primers_text = (await primers_csv.read()).decode("utf-8-sig", errors="replace")
    tags_text = (await tags_csv.read()).decode("utf-8-sig", errors="replace")
    try:
        primers = parse_primers_csv(primers_text)
        tag_columns = parse_tag_columns(tags_text)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return {"primers": primers, "tag_columns": tag_columns}
