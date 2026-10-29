"""Generate kit codes of the form `<panel>_<YYMMDD>_<NN>`, e.g. `Bearplex_261029_01`.

The lab names kits after the assay, so the code is built from the panel's own code — rename a
panel in Admin → Panels and the next batch follows the new name. Codes already issued never
change: they are printed on stickers, so a kit's code is a snapshot of the day it was registered,
not something derived live.

Numbering restarts each day for each panel, which keeps the trailing number short and means a
consignment reads 01..10.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Kit

# kit_code is String(64), and the code also prefixes every control well name
# (`<kit_code>_blank_A1`), so a long panel name hurts twice.
MAX_KIT_CODE_LEN = 64


def date_token(on: date | None = None) -> str:
    return (on or date.today()).strftime("%y%m%d")


def _suffix_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(prefix)}(\d+)$")


def next_codes(db: Session, panel_code: str, count: int, on: date | None = None) -> list[str]:
    """The next `count` codes for this panel today, continuing from whatever already exists.

    Reads the highest number currently used for this panel and date rather than counting rows, so
    a deleted kit never causes a code to be reused — a reissued code would collide with a sticker
    already in the post.
    """
    prefix = f"{panel_code}_{date_token(on)}_"

    used = db.scalars(select(Kit.kit_code).where(Kit.kit_code.like(f"{prefix}%"))).all()
    pattern = _suffix_pattern(prefix)
    highest = 0
    for code in used:
        m = pattern.match(code)
        if m:
            highest = max(highest, int(m.group(1)))

    # Two digits normally; widens rather than failing if a panel ever passes 99 in one day.
    codes = []
    for n in range(highest + 1, highest + 1 + count):
        codes.append(f"{prefix}{n:02d}")
    return codes


def check_length(codes: list[str]) -> str | None:
    """The reason these codes are unusable, or None. Checked before anything is written."""
    too_long = [c for c in codes if len(c) > MAX_KIT_CODE_LEN]
    if not too_long:
        return None
    return (
        f"the generated kit code {too_long[0]!r} is {len(too_long[0])} characters, over the "
        f"{MAX_KIT_CODE_LEN} allowed. Give the panel a shorter name in Admin → Panels "
        "(it is used as the code's prefix)."
    )
