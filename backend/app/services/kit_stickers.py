"""Build the .xlsx the lab prints shipping stickers from: one row per kit, code and claim code.

This formats data it is handed and stores nothing, which is not a shortcut — it is the only way
the sheet can exist. Claim codes are kept as keyed hashes (services/claim_codes.py), so the
plaintext lives in the response that created the kits and nowhere else. A sheet rebuilt later
could only contain codes that had been regenerated, invalidating any sticker already printed.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADERS = ["Kit code", "Claim code", "Species", "Panel", "Registered", "Sent to"]
_HEADER_FILL = PatternFill("solid", fgColor="E5E7EB")
_WIDTHS = [26, 24, 20, 20, 13, 28]


def build_sticker_sheet(rows: list[dict]) -> bytes:
    """`rows`: dicts with kit_code, claim_code, species, panel, registered.

    "Sent to" is left empty on purpose — it is the column the person packing the boxes fills in.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "kits"

    for i, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=i, value=header)
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
        ws.column_dimensions[cell.column_letter].width = _WIDTHS[i - 1]

    for r, row in enumerate(rows, start=2):
        ws.cell(row=r, column=1, value=row.get("kit_code")).font = Font(bold=True)
        claim = ws.cell(row=r, column=2, value=row.get("claim_code"))
        # Monospaced and roomy: this is the string somebody retypes from a sticker.
        claim.font = Font(name="Menlo", size=11)
        claim.alignment = Alignment(horizontal="left")
        ws.cell(row=r, column=3, value=row.get("species"))
        ws.cell(row=r, column=4, value=row.get("panel"))
        ws.cell(row=r, column=5, value=row.get("registered"))

    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
