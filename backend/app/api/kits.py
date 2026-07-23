"""Kit catalog: admin registers kits from panels + tag columns; per-user access; status."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    User, Kit, KitReads, TagColumn, Control, PrimerPanel, TagLayout, KitStatus, kit_access,
)
from app.auth.deps import get_current_user, require_admin
from app.schemas.kit import (
    KitCreate, KitUpdate, KitOut, KitSummary, KitReadsIn, KitReadsOut, ClaimRequest,
)
from app.schemas.panel import TagLayoutOut
from app.services import storage
from app.services.kit_reads import set_kit_reads
from app.services import claim_codes

router = APIRouter(prefix="/kits", tags=["kits"])


def _pp_ordinal(name: str) -> int:
    m = re.findall(r"\d+", name)
    return int(m[0]) if m else 0


_WELL_RE = re.compile(r"^[A-H](1[0-2]|[1-9])$")   # A1..H12


def _build_controls(kit_code: str, controls_in) -> list[Control]:
    """Validate wells (unique standard A1..H12) and resolve auto-names for position controls."""
    rows: list[Control] = []
    seen: set[str] = set()
    for c in controls_in:
        pos = (c.position or "").strip().upper() or None
        if pos is not None:
            if not _WELL_RE.match(pos):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid control well: {c.position!r}"
                )
            if pos in seen:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"duplicate control well: {pos}"
                )
            seen.add(pos)
        name = (c.name or "").strip() or (f"{kit_code}_{c.kind.name_token}_{pos}" if pos else None)
        rows.append(Control(kind=c.kind, name_pattern=c.name_pattern, position=pos, name=name))
    return rows


def _global_tag_layout(db: Session) -> TagLayout:
    layout = db.scalar(select(TagLayout).order_by(TagLayout.id))
    if layout is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No tag layout configured (seed it first)")
    return layout


def _can_access(kit: Kit, user: User) -> bool:
    return user.is_admin or any(u.id == user.id for u in kit.users)


def _attach_claim_emails(db: Session, kits: list[Kit]) -> None:
    """Set the transient `claimed_by_email` (read by Kit{Summary,Out}) for a batch of kits."""
    ids = {k.claimed_by for k in kits if k.claimed_by}
    emails = dict(db.execute(select(User.id, User.email).where(User.id.in_(ids))).all()) if ids else {}
    for k in kits:
        k.claimed_by_email = emails.get(k.claimed_by) if k.claimed_by else None


# ---------- tag layout (for the admin kit form) ----------

@router.get("/tag-layout", response_model=TagLayoutOut)
def get_tag_layout(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _global_tag_layout(db)


# ---------- list / get (access-filtered) ----------

@router.get("", response_model=list[KitSummary])
def list_kits(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """Admins see all kits; non-admins see only kits granted to them."""
    from sqlalchemy.orm import selectinload
    stmt = select(Kit).options(selectinload(Kit.reads)).order_by(Kit.kit_code)
    if not current.is_admin:
        stmt = stmt.join(kit_access, kit_access.c.kit_id == Kit.id).where(
            kit_access.c.user_id == current.id
        )
    kits = db.scalars(stmt).all()
    # attach each kit's linked studies (for the Submit page's ingestion-target pre-fill)
    from collections import defaultdict
    from app.models import study_kits, Study
    from app.schemas.kit import KitStudyRef
    by_kit: dict[int, list] = defaultdict(list)
    if kits:
        rows = db.execute(
            select(study_kits.c.kit_id, Study.id, Study.name, Study.project_id, Study.population_id)
            .join(Study, Study.id == study_kits.c.study_id)
            .where(study_kits.c.kit_id.in_([k.id for k in kits]))
        ).all()
        for kid, sid, sname, pid, popid in rows:
            by_kit[kid].append(KitStudyRef(id=sid, name=sname, project_id=pid, population_id=popid))
    for k in kits:
        k.studies = by_kit.get(k.id, [])   # transient attr read by KitSummary
    _attach_claim_emails(db, list(kits))
    return kits


@router.get("/{kit_id}/control-template.xlsx")
def download_control_template(
    kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    """A plate .xlsx pre-filled with this kit's control names — ready for the upload path."""
    from app.services.control_sheet import build_control_template_xlsx
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    if not _can_access(kit, current):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
    data = build_control_template_xlsx(kit)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kit.kit_code}_plate_template.xlsx"'},
    )


# ---------- per-kit server-side FASTQ reads ----------

def _reads_out(db: Session, r: KitReads) -> KitReadsOut:
    email = db.get(User, r.uploaded_by).email if r.uploaded_by else None
    return KitReadsOut(
        fastq1_key=r.fastq1_key, fastq2_key=r.fastq2_key,
        fastq1_name=r.fastq1_name, fastq2_name=r.fastq2_name,
        size1=r.size1, size2=r.size2, uploaded_at=r.uploaded_at, uploaded_by_email=email,
    )


def _load_kit(kit_id: int, db: Session, current: User) -> Kit:
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    if not _can_access(kit, current):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
    return kit


@router.get("/{kit_id}/reads", response_model=KitReadsOut | None)
def get_kit_reads(kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    kit = _load_kit(kit_id, db, current)
    return _reads_out(db, kit.reads) if kit.reads else None


@router.put("/{kit_id}/reads", response_model=KitReadsOut)
def put_kit_reads(
    kit_id: int, payload: KitReadsIn,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    kit = _load_kit(kit_id, db, current)
    prefix = f"reads/kit/{kit_id}/"
    for key in (payload.fastq1_key, payload.fastq2_key):
        if not key.startswith(prefix):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "reads must be uploaded to this kit before registering")
        if not storage.object_exists(key):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"uploaded object missing: {key}")
    r = set_kit_reads(
        db, kit, fastq1_key=payload.fastq1_key, fastq2_key=payload.fastq2_key,
        fastq1_name=payload.fastq1_name, fastq2_name=payload.fastq2_name,
        size1=payload.size1, size2=payload.size2, uploaded_by=current.id,
    )
    db.commit()
    return _reads_out(db, r)


@router.delete("/{kit_id}/reads", status_code=status.HTTP_204_NO_CONTENT)
def delete_kit_reads(kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    kit = _load_kit(kit_id, db, current)
    if kit.reads:
        storage.delete_object(kit.reads.fastq1_key)
        storage.delete_object(kit.reads.fastq2_key)
        db.delete(kit.reads)
        db.commit()


@router.get("/{kit_id}", response_model=KitOut)
def get_kit(kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    if not _can_access(kit, current):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
    _attach_claim_emails(db, [kit])
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
        controls=_build_controls(payload.kit_code, payload.controls),
        users=list(assigned),
    )
    code = claim_codes.assign_new_code(kit)   # store hmac; return plaintext once (below)
    db.add(kit)
    db.commit()
    db.refresh(kit)
    kit.claim_code = code                     # transient — serialized in KitOut this once only
    return kit


# ---------- claim codes (self-service kit access) ----------

@router.post("/claim", response_model=KitOut)
def claim_kit(payload: ClaimRequest, db: Session = Depends(get_db),
              current: User = Depends(get_current_user)):
    """Redeem a kit's claim code — attaches the kit to the current user."""
    try:
        kit = claim_codes.redeem(db, current, payload.code)
    except claim_codes.CodeNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid or unknown kit code")
    except claim_codes.AlreadyClaimed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This kit has already been claimed")
    db.commit()
    db.refresh(kit)
    _attach_claim_emails(db, [kit])
    return kit


@router.post("/{kit_id}/claim-code", response_model=KitOut)
def regenerate_claim_code(kit_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Issue a fresh claim code for a kit (invalidates the old one). Returns the plaintext once."""
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    code = claim_codes.assign_new_code(kit)
    db.commit()
    db.refresh(kit)
    kit.claim_code = code
    _attach_claim_emails(db, [kit])
    return kit


@router.delete("/{kit_id}/claim", response_model=KitOut)
def revoke_claim(kit_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Detach the claimer from a kit (admin override)."""
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    kit.users = [u for u in kit.users if u.id != kit.claimed_by]
    kit.claimed_by = None
    kit.claimed_at = None
    db.commit()
    db.refresh(kit)
    _attach_claim_emails(db, [kit])
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
