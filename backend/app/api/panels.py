"""Primer-panel catalog (admin): the reusable per-species primer sets kits are built from."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Kit, PrimerPanel, Primer, PrimerType
from app.auth.deps import require_admin
from app.services import storage
from app.services.kit_files import parse_primers_csv
from app.schemas.panel import PanelOut, PanelSummary, PanelUpdate

router = APIRouter(prefix="/panels", tags=["panels"])


@router.get("", response_model=list[PanelSummary])
def list_panels(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(PrimerPanel).order_by(PrimerPanel.code)).all()


@router.get("/{panel_id}", response_model=PanelOut)
def get_panel(panel_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    panel = db.get(PrimerPanel, panel_id)
    if panel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Panel not found")
    return panel


@router.get("/{panel_id}/download")
def download_panel(panel_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Presigned URL to download the panel's primers CSV."""
    panel = db.get(PrimerPanel, panel_id)
    if panel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Panel not found")
    if not panel.primers_csv_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Panel has no stored CSV")
    return {"url": storage.presign_get(panel.primers_csv_key, filename=f"{panel.code}.csv")}


@router.patch("/{panel_id}", response_model=PanelOut)
def update_panel(
    panel_id: int, payload: PanelUpdate,
    db: Session = Depends(get_db), _: User = Depends(require_admin),
):
    panel = db.get(PrimerPanel, panel_id)
    if panel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Panel not found")
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] != panel.code:
        if db.scalar(select(PrimerPanel).where(PrimerPanel.code == data["code"])):
            raise HTTPException(status.HTTP_409_CONFLICT, "panel code already exists")
    for k, v in data.items():
        setattr(panel, k, v)
    db.commit()
    db.refresh(panel)
    return panel


@router.delete("/{panel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_panel(panel_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    panel = db.get(PrimerPanel, panel_id)
    if panel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Panel not found")
    in_use = db.scalar(select(Kit).where(Kit.panel_id == panel_id))
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"panel is used by kit {in_use.kit_code!r}; reassign or delete that kit first",
        )
    db.delete(panel)
    db.commit()


@router.post("", response_model=PanelOut, status_code=status.HTTP_201_CREATED)
async def create_panel(
    code: str = Form(...),
    species_common: str | None = Form(None),
    species_latin: str | None = Form(None),
    description: str | None = Form(None),
    primers_csv: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Add a new panel: upload its primers CSV, which is parsed and stored in S3."""
    if db.scalar(select(PrimerPanel).where(PrimerPanel.code == code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "panel code already exists")

    raw = await primers_csv.read()
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        rows = parse_primers_csv(text)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    key = f"panels/{code}.csv"
    storage.put_bytes(key, raw)  # store the exact bytes the pipeline will read

    panel = PrimerPanel(
        code=code,
        species_common=species_common,
        species_latin=species_latin,
        description=description,
        primers_csv_key=key,
        primers=[
            Primer(
                locus=r["locus"], type=PrimerType(r["type"]),
                primer_f=r["primer_f"], primer_r=r["primer_r"],
                motif=r["motif"], sequence=r["sequence"],
            )
            for r in rows
        ],
    )
    db.add(panel)
    db.commit()
    db.refresh(panel)
    return panel
