"""Seed the primer-panel catalog + the single shared tag layout from bundled reference CSVs.

The CSVs live in backend/seed_data/ (bundled so they ship in the image). Species labels are a
best-guess map and are admin-editable afterwards. Idempotent: skips panels/layout already present.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, func

from app.db import SessionLocal
from app.models import PrimerPanel, Primer, PrimerType, TagLayout
from app.services.kit_files import parse_primers_csv, parse_tag_columns
from app.services import storage

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"

# code-prefix -> (common name, latin name). Admin-editable after seeding.
SPECIES = {
    "UA": ("brown bear", "Ursus arctos"),
    "LL": ("Eurasian lynx", "Lynx lynx"),
    "CL": ("grey wolf", "Canis lupus"),
    "CE": ("red deer", "Cervus elaphus"),
    "TuTr": ("bottlenose dolphin", "Tursiops truncatus"),
    "sex": ("lynx (sex markers)", "Lynx lynx"),
}


def _species_for(code: str) -> tuple[str, str | None]:
    prefix = code.split("_")[0]
    return SPECIES.get(prefix, (prefix, None))


def seed_catalog(db=None, upload_to_s3: bool = True) -> None:
    close = db is None
    db = db or SessionLocal()
    try:
        for f in sorted((SEED_DIR / "panels").glob("*.csv")):
            code = f.stem  # e.g. "UA_primers", "LL_MPA_primers"
            if db.scalar(select(PrimerPanel).where(PrimerPanel.code == code)):
                continue
            try:
                rows = parse_primers_csv(f.read_text(encoding="utf-8-sig"))
            except ValueError:
                continue  # skip anything unparseable
            common, latin = _species_for(code)
            key = f"panels/{code}.csv"
            if upload_to_s3:
                storage.put_bytes(key, f.read_bytes())
            db.add(PrimerPanel(
                code=code, species_common=common, species_latin=latin, primers_csv_key=key,
                primers=[
                    Primer(locus=r["locus"], type=PrimerType(r["type"]),
                           primer_f=r["primer_f"], primer_r=r["primer_r"],
                           motif=r["motif"], sequence=r["sequence"])
                    for r in rows
                ],
            ))

        if not db.scalar(select(TagLayout)):
            tags_file = SEED_DIR / "tags.csv"
            cols = [c["name"] for c in parse_tag_columns(tags_file.read_text(encoding="utf-8-sig"))]
            key = "tags/tags.csv"
            if upload_to_s3:
                storage.put_bytes(key, tags_file.read_bytes())
            db.add(TagLayout(name="default", tags_csv_key=key, column_names=cols))

        db.commit()
        n = db.scalar(select(func.count()).select_from(PrimerPanel))
        print(f"catalog seeded: {n} primer panels + 1 tag layout")
    finally:
        if close:
            db.close()


if __name__ == "__main__":
    seed_catalog()
