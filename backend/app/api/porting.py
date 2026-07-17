"""Import / export endpoints for a project's structured data."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth.deps import get_current_user
from app.auth.access import get_accessible_project
from app.models import User
from app.services import porting

router = APIRouter(tags=["porting"])

_CSV_EXPORTS = {
    "genotypes": ("genotypes.csv", "text/csv", porting.genotypes_csv),
    "metadata": ("samples_metadata.csv", "text/csv", porting.metadata_csv),
    "animals": ("animals.csv", "text/csv", porting.animals_csv),
    "genepop": ("genepop.txt", "text/plain", porting.genepop),
}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "project"


@router.get("/projects/{project_id}/export/{kind}")
def export_project(
    project_id: int, kind: str,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    project = get_accessible_project(project_id, db=db, user=current)
    if kind == "json":
        content = json.dumps(porting.project_json(db, project_id), indent=2)
        return Response(content, media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="{_slug(project.name)}.json"'})
    if kind not in _CSV_EXPORTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown export kind {kind!r}")
    filename, media_type, fn = _CSV_EXPORTS[kind]
    return Response(fn(db, project_id), media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/projects/{project_id}/import/genotypes")
async def import_genotypes(
    project_id: int, file: UploadFile = File(...),
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, need_edit=True, db=db, user=current)
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    try:
        summary = porting.import_genotypes(db, project_id, text)   # auto-detects wide vs long
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    db.commit()
    return summary


@router.post("/projects/import", status_code=status.HTTP_201_CREATED)
async def import_project(
    file: UploadFile = File(...),
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    try:
        data = json.loads((await file.read()).decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "file is not valid JSON")
    if not isinstance(data, dict) or "project" not in data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "not a STReamGT project export (missing 'project')")
    project = porting.import_project_json(db, current.id, data)
    db.commit()
    db.refresh(project)
    return {"id": project.id, "public_id": project.public_id, "name": project.name}
