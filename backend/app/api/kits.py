"""Kit catalog: admin registers kits from panels + tag columns; per-user access; status."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    User, Kit, KitReads, TagColumn, Control, PrimerPanel, TagLayout, KitStatus, kit_access,
)
from app.auth.deps import get_current_user, require_admin
from app.schemas.kit import (
    KitCreate, KitUpdate, KitOut, KitSummary, KitReadsIn, KitReadsOut, ClaimRequest,
    KitBatchCreate, KitBatchOut, KitStickerRow, KitStickerSheetRequest,
    KitSetupIn, KitSetupOut, ReadDownload,
)
from app.schemas.panel import TagLayoutOut
from app.services import storage
from app.services.kit_files import parse_tag_columns
from app.services.kit_reads import set_kit_reads
from app.services import kit_setup
from app.services import claim_codes
from app.services import kit_codes
from app.services import ratelimit

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


@router.get("/tag-layout/download")
def download_tag_layout(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Presigned URL to download the current shared tags CSV."""
    layout = _global_tag_layout(db)
    if not layout.tags_csv_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No tags CSV stored")
    return {"url": storage.presign_get(layout.tags_csv_key, filename="tags.csv")}


@router.post("/tag-layout", response_model=TagLayoutOut)
async def upload_tag_layout(
    tags_csv: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Replace the shared tag layout (Position,PP1,PP2,… CSV). Applies to all kits."""
    raw = await tags_csv.read()
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        cols = parse_tag_columns(text)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    key = "tags/tags.csv"                 # canonical key the pipeline reads
    storage.put_bytes(key, raw)

    layout = db.scalar(select(TagLayout).order_by(TagLayout.id))
    if layout is None:
        layout = TagLayout(name="default")
        db.add(layout)
    layout.tags_csv_key = key
    layout.column_names = [c["name"] for c in cols]
    db.commit()
    db.refresh(layout)
    return layout


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


@router.get("/export.xlsx")
def export_kits(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Every kit as a spreadsheet: what exists, who holds it, and where it has got to.

    Without claim codes, deliberately: this is the file that gets emailed around. The sticker
    sheet below is the one that carries them.
    """
    from sqlalchemy.orm import selectinload
    from app.services.kit_stickers import build_kit_inventory

    kits = list(db.scalars(
        select(Kit)
        .options(selectinload(Kit.panel), selectinload(Kit.tag_columns))
        .order_by(Kit.kit_code)
    ).all())
    _attach_claim_emails(db, kits)

    data = build_kit_inventory(kits)
    name = f"streamgt_kits_{date.today():%Y%m%d}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/stickers.xlsx")
def download_sticker_sheet(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Reprint the claim-code sheet for every kit whose code can still be read back.

    Declared before `/{kit_id}`, like export.xlsx: the other order matches "stickers.xlsx" as a
    kit id and answers 422.

    A kit is here only while its code is still worth printing — claiming clears the sealed copy,
    and kits registered before sealing existed never had one. Regenerating a code on the Kits
    page puts a kit back in this sheet.
    """
    from sqlalchemy.orm import selectinload
    from app.services.kit_stickers import build_sticker_sheet

    kits = db.scalars(
        select(Kit)
        .options(selectinload(Kit.panel))
        .where(Kit.claim_code_sealed.is_not(None))
        .order_by(Kit.kit_code)
    ).all()

    rows = []
    for kit in kits:
        code = claim_codes.printable_code(kit)
        if code is None:
            continue    # sealed under a retired key: unreadable, not an error
        rows.append({
            "kit_code": kit.kit_code,
            "claim_code": code,
            "species": kit.species,
            "panel": kit.panel.code if kit.panel else None,
            "registered": kit.created_at.date().isoformat() if kit.created_at else None,
        })
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No kit has a printable claim code. Claiming a kit clears its code, and kits "
            "registered before codes were kept cannot be reprinted — use 'code' on a kit to "
            "issue a fresh one.",
        )

    name = f"streamgt_claim_codes_{date.today():%Y%m%d}.xlsx"
    return Response(
        content=build_sticker_sheet(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


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


@router.get("/{kit_id}/reads/download", response_model=list[ReadDownload])
def download_kit_reads(
    kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    """Presigned links to the kit's FASTQ pair — the same gate as uploading them.

    Until now an upload was write-only: presign_get was reachable only for results, the tag layout
    and panel CSVs, so nobody could check what they had sent or retrieve their own raw data.

    The size comes from S3 rather than from kit_reads, which records it only when the pair was
    registered through PUT /reads and not when a submission adopted it. Asking S3 is true by
    construction and doubles as a check that the object is still there before a link is handed out.
    """
    kit = _load_kit(kit_id, db, current)
    if kit.reads is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This kit has no reads stored on the server.")

    out = []
    for key, name in ((kit.reads.fastq1_key, kit.reads.fastq1_name),
                      (kit.reads.fastq2_key, kit.reads.fastq2_name)):
        size = storage.object_size(key)
        if size is None:
            raise HTTPException(
                status.HTTP_410_GONE,
                "The stored reads are no longer in storage. Upload the pair again.",
            )
        filename = name or key.rsplit("/", 1)[-1]
        out.append(ReadDownload(
            filename=filename, url=storage.presign_get(key, filename), size_bytes=size,
        ))
    return out


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


# ---------- per-kit analysis setup (the sheet filled in before the FASTQ arrives) ----------

def _setup_out(db: Session, row) -> KitSetupOut:
    email = db.get(User, row.updated_by).email if row.updated_by else None
    return KitSetupOut(
        project_id=row.project_id,
        default_population_id=row.default_population_id,
        default_study_id=row.default_study_id,
        expected_read_number=row.expected_read_number,
        parameters=row.parameters,
        batches=row.batches or [],
        updated_at=row.updated_at,
        updated_by_email=email,
    )


@router.get("/{kit_id}/analysis-setup", response_model=KitSetupOut | None)
def get_kit_setup(
    kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    """The saved setup for this kit's next run, or null if nobody has saved one."""
    kit = _load_kit(kit_id, db, current)
    return _setup_out(db, kit.analysis_setup) if kit.analysis_setup else None


@router.put("/{kit_id}/analysis-setup", response_model=KitSetupOut)
def put_kit_setup(
    kit_id: int, payload: KitSetupIn,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Save the sheet. Deliberately accepts an incomplete one — it is a draft, not a submission.

    None of POST /jobs' completeness rules are applied here (tag columns belonging to the kit, at
    least one batch, a full 96-well plate). They still hold at submission; a half-finished sheet
    that could not be saved would defeat the point.
    """
    kit = _load_kit(kit_id, db, current)
    row = kit_setup.save_setup(
        db, kit,
        project_id=payload.project_id,
        default_population_id=payload.default_population_id,
        default_study_id=payload.default_study_id,
        expected_read_number=payload.expected_read_number,
        parameters=payload.parameters,
        batches=[b.model_dump() for b in payload.batches],
        updated_by=current.id,
    )
    db.commit()
    db.refresh(row)
    return _setup_out(db, row)


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
    )
    code = claim_codes.assign_new_code(kit)   # hashed + sealed; plaintext returned once (below)
    db.add(kit)
    db.commit()
    db.refresh(kit)
    kit.claim_code = code                     # transient — serialized in KitOut this once only
    return kit


@router.post("/batch", response_model=KitBatchOut, status_code=status.HTTP_201_CREATED)
def create_kit_batch(
    payload: KitBatchCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    """Register a consignment of kits in one go, naming them after the panel and today's date.

    All or nothing: one transaction, one commit. A partial batch would leave the printed sticker
    sheet disagreeing with the database, which is worse than registering none.

    The response carries each kit's claim code in plaintext, ready for the sticker sheet. An
    encrypted copy is kept too, so the sheet can be reprinted from the Kits page until the kit is
    claimed.
    """
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

    codes = kit_codes.next_codes(db, panel.code, payload.count)
    too_long = kit_codes.check_length(codes)
    if too_long:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, too_long)

    rows: list[KitStickerRow] = []
    registered = date.today().isoformat()
    for kit_code in codes:
        kit = Kit(
            kit_code=kit_code,
            panel_id=panel.id,
            species=panel.species_common,
            description=payload.description,
            status=payload.status,
            primers_csv_key=panel.primers_csv_key,
            tags_csv_key=layout.tags_csv_key,
            created_by=admin.id,
            tag_columns=[TagColumn(name=t, ordinal=_pp_ordinal(t)) for t in payload.selected_tags],
            # Re-resolved per kit: control wells are named after the kit they belong to.
            controls=_build_controls(kit_code, payload.controls),
        )
        plaintext = claim_codes.assign_new_code(kit)
        db.add(kit)
        rows.append(KitStickerRow(
            kit_code=kit_code, claim_code=plaintext,
            species=panel.species_common, panel=panel.code, registered=registered,
        ))

    try:
        db.commit()
    except IntegrityError:
        # Another batch for the same panel landed between picking the numbers and committing.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another batch was registered at the same moment and took these codes. "
            "Nothing was created — please try again.",
        )

    return KitBatchOut(
        kits=rows, panel=panel.code, species=panel.species_common, registered=registered,
    )


@router.post("/batch/stickers.xlsx")
def kit_batch_sticker_sheet(
    payload: KitStickerSheetRequest, _: User = Depends(require_admin),
):
    """Format one registration's codes as the spreadsheet the lab prints stickers from.

    A POST that echoes back the rows it is handed, which is what keeps it to exactly the kits just
    registered — the filename says which consignment it is. `GET /stickers.xlsx` is the other
    half: every kit still printable, for when this sheet was lost.
    """
    from app.services.kit_stickers import build_sticker_sheet

    data = build_sticker_sheet([r.model_dump() for r in payload.rows])
    first = payload.rows[0]
    name = f"{first.panel or 'kits'}_{(first.registered or '').replace('-', '')}_codes.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------- claim codes (self-service kit access) ----------

@router.post("/claim", response_model=KitOut, dependencies=[Depends(ratelimit.limit("claim"))])
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
        # Only touch the description when the caller actually sent the field: a PATCH that omits
        # it must leave it alone (the admin UI once sent description="" with every status change
        # and silently wiped it), while an explicit "" still clears it.
        if "description" in payload.model_fields_set:
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
    from app.models import Job, Sample
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    if kit.status == KitStatus.analysed:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This kit has been analysed and cannot be deleted.")
    if db.scalar(select(Job.id).where(Job.kit_id == kit.id).limit(1)) \
            or db.scalar(select(Sample.id).where(Sample.kit_id == kit.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This kit is in use (has analysis jobs or samples) and cannot be deleted.")
    db.delete(kit)
    db.commit()
