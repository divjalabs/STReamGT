"""Registering a consignment of kits in one go, and the sheet the lab prints stickers from.

A code on a sticker is useless unless it is the one the database will accept, so these tests care
as much about the codes reaching the caller intact — at registration and on a later reprint — as
about the rows landing in the database.
"""
from __future__ import annotations

import io
from datetime import date

from openpyxl import load_workbook
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Kit
from app.services import claim_codes
from tests.conftest import bearer, panel_id, register


def _batch(client, token, count=3, panel="UA_primers", **over):
    payload = {
        "panel_id": panel_id(panel),
        "count": count,
        "selected_tags": ["PP1", "PP2", "PP3", "PP4"],
        **over,
    }
    return client.post("/api/kits/batch", json=payload, headers=bearer(token))


def test_codes_are_named_after_the_panel_and_today(client, catalog, admin_token):
    r = _batch(client, admin_token, count=3)
    assert r.status_code == 201, r.text
    codes = [k["kit_code"] for k in r.json()["kits"]]

    today = date.today().strftime("%y%m%d")
    assert codes == [f"UA_primers_{today}_01", f"UA_primers_{today}_02", f"UA_primers_{today}_03"]
    assert r.json()["species"] == "brown bear"


def test_a_second_batch_the_same_day_continues_the_numbering(client, catalog, admin_token):
    _batch(client, admin_token, count=2)
    r = _batch(client, admin_token, count=2)
    today = date.today().strftime("%y%m%d")
    assert [k["kit_code"] for k in r.json()["kits"]] == [
        f"UA_primers_{today}_03", f"UA_primers_{today}_04",
    ]


def test_each_panel_numbers_independently(client, catalog, admin_token):
    _batch(client, admin_token, count=2, panel="UA_primers")
    r = _batch(client, admin_token, count=1, panel="CL_MPABC_primers")
    today = date.today().strftime("%y%m%d")
    assert r.json()["kits"][0]["kit_code"] == f"CL_MPABC_primers_{today}_01"
    assert r.json()["species"] == "grey wolf"


def test_every_kit_gets_its_own_working_claim_code(client, catalog, admin_token):
    """The point of the spreadsheet: these codes must be the ones the database will accept."""
    rows = _batch(client, admin_token, count=3).json()["kits"]
    plaintexts = [r["claim_code"] for r in rows]
    assert len(set(plaintexts)) == 3, "each kit needs its own code"

    with SessionLocal() as db:
        for row in rows:
            kit = db.scalar(select(Kit).where(Kit.kit_code == row["kit_code"]))
            assert kit.claim_code_hmac == claim_codes.hmac_code(row["claim_code"])
            assert row["claim_code"] not in (kit.claim_code_hmac or "")   # never stored as text


def test_a_claim_code_from_a_batch_can_be_redeemed(client, catalog, admin_token):
    row = _batch(client, admin_token, count=1).json()["kits"][0]
    user = register(client, "batch-claimer@lab.org")
    r = client.post("/api/kits/claim", json={"code": row["claim_code"]}, headers=bearer(user))
    assert r.status_code == 200, r.text
    assert r.json()["kit_code"] == row["kit_code"]


def test_controls_are_named_per_kit(client, catalog, admin_token):
    r = _batch(client, admin_token, count=2, controls=[
        {"kind": "sequencing", "position": "A1"},
    ])
    codes = [k["kit_code"] for k in r.json()["kits"]]
    with SessionLocal() as db:
        for code in codes:
            kit = db.scalar(select(Kit).where(Kit.kit_code == code))
            assert kit.controls[0].name == f"{code}_blank_A1", "each kit names its own wells"


def test_nothing_is_created_when_the_batch_is_rejected(client, catalog, admin_token):
    before = _count_kits()
    r = _batch(client, admin_token, count=2, selected_tags=["PP1", "NOPE"])
    assert r.status_code == 422
    assert _count_kits() == before, "a rejected batch must leave no kits behind"


def test_a_panel_cannot_be_named_something_unusable(client, catalog, admin_token):
    """The panel code becomes the kit code, which becomes an S3 prefix and control well names."""
    pid = panel_id("UA_primers")

    for bad in ["X" * 60, "bear/plex", "bear plex", ""]:
        r = client.patch(f"/api/panels/{pid}", json={"code": bad}, headers=bearer(admin_token))
        assert r.status_code == 422, f"{bad!r} should be refused"
        assert "letters, digits" in r.json()["detail"]

    ok = client.patch(f"/api/panels/{pid}", json={"code": "Bearplex"}, headers=bearer(admin_token))
    assert ok.status_code == 200 and ok.json()["code"] == "Bearplex"


def test_renaming_a_panel_renames_only_future_kits(client, catalog, admin_token):
    """Codes already issued are printed on stickers — they must never move."""
    before = _batch(client, admin_token, count=1).json()["kits"][0]["kit_code"]
    pid = panel_id("UA_primers")
    client.patch(f"/api/panels/{pid}", json={"code": "Bearplex"}, headers=bearer(admin_token))

    after = client.post(
        "/api/kits/batch",
        json={"panel_id": pid, "count": 1, "selected_tags": ["PP1"]},
        headers=bearer(admin_token),
    ).json()["kits"][0]["kit_code"]

    assert before.startswith("UA_primers_")
    assert after.startswith("Bearplex_")
    with SessionLocal() as db:
        assert db.scalar(select(Kit).where(Kit.kit_code == before)) is not None, \
            "the already-registered kit keeps its original code"


def test_over_long_generated_codes_are_caught(client, catalog):
    """Belt and braces behind the panel-code limit: kit_code is capped at 64 characters."""
    from app.services import kit_codes

    assert kit_codes.check_length(["A" * 60 + "_261029_01"]) is not None
    assert kit_codes.check_length(["Bearplex_261029_01"]) is None


def test_only_admins_may_register_a_batch(client, catalog, user_token):
    assert _batch(client, user_token, count=1).status_code == 403


# --- the spreadsheet ---------------------------------------------------------------------

def test_sticker_sheet_has_a_row_per_kit(client, catalog, admin_token):
    batch = _batch(client, admin_token, count=2).json()
    r = client.post("/api/kits/batch/stickers.xlsx", json={"rows": batch["kits"]},
                    headers=bearer(admin_token))
    assert r.status_code == 200
    assert "spreadsheet" in r.headers["content-type"]
    assert ".xlsx" in r.headers["content-disposition"]

    ws = load_workbook(io.BytesIO(r.content)).active
    assert [c.value for c in ws[1]][:2] == ["Kit code", "Claim code"]
    assert ws.max_row == 3    # header + two kits
    assert ws.cell(row=2, column=1).value == batch["kits"][0]["kit_code"]
    assert ws.cell(row=2, column=2).value == batch["kits"][0]["claim_code"]
    assert ws.cell(row=2, column=6).value is None, "'Sent to' is for the lab to fill in"


def _count_kits() -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Kit)).all())


# --- the kit inventory export ------------------------------------------------------------

def test_kit_export_lists_every_kit_without_claim_codes(client, catalog, admin_token):
    batch = _batch(client, admin_token, count=2).json()
    r = client.get("/api/kits/export.xlsx", headers=bearer(admin_token))
    assert r.status_code == 200
    assert "spreadsheet" in r.headers["content-type"]

    ws = load_workbook(io.BytesIO(r.content)).active
    headers = [c.value for c in ws[1]]
    assert headers[:3] == ["Kit code", "Species", "Panel"]
    assert "Claim code" not in headers, "claim codes are hashed — they cannot appear here"

    codes = {ws.cell(row=r_, column=1).value for r_ in range(2, ws.max_row + 1)}
    assert {k["kit_code"] for k in batch["kits"]} <= codes

    # And no claim code leaked into any cell.
    plaintexts = {k["claim_code"] for k in batch["kits"]}
    all_cells = {str(c.value) for row in ws.iter_rows() for c in row}
    assert not (plaintexts & all_cells)


def test_kit_export_is_admin_only(client, catalog, user_token):
    assert client.get("/api/kits/export.xlsx", headers=bearer(user_token)).status_code == 403


# --- reprinting the sheet ----------------------------------------------------------------
# The sealed copy (services/code_vault.py) exists so that closing the page is survivable. These
# tests care that what comes back out is the code the database will actually accept.

def test_the_sheet_can_be_downloaded_again_later(client, catalog, admin_token):
    batch = _batch(client, admin_token, count=2).json()

    r = client.get("/api/kits/stickers.xlsx", headers=bearer(admin_token))
    assert r.status_code == 200
    assert "spreadsheet" in r.headers["content-type"]

    ws = load_workbook(io.BytesIO(r.content)).active
    assert [c.value for c in ws[1]][:2] == ["Kit code", "Claim code"]
    printed = {
        ws.cell(row=i, column=1).value: ws.cell(row=i, column=2).value
        for i in range(2, ws.max_row + 1)
    }
    for row in batch["kits"]:
        assert printed[row["kit_code"]] == row["claim_code"]


def test_a_reprinted_code_still_redeems(client, catalog, admin_token):
    """The whole feature in one assertion: the reprint is usable, not just plausible."""
    _batch(client, admin_token, count=1)
    sheet = client.get("/api/kits/stickers.xlsx", headers=bearer(admin_token))
    reprinted = load_workbook(io.BytesIO(sheet.content)).active.cell(row=2, column=2).value

    user = register(client, "reprint-claimer@lab.org")
    r = client.post("/api/kits/claim", json={"code": reprinted}, headers=bearer(user))
    assert r.status_code == 200, r.text


def test_claiming_takes_a_kit_off_the_sheet(client, catalog, admin_token):
    """Once claimed the code is inert, so the readable copy is destroyed rather than kept."""
    row = _batch(client, admin_token, count=1).json()["kits"][0]
    user = register(client, "off-the-sheet@lab.org")
    assert client.post("/api/kits/claim", json={"code": row["claim_code"]},
                       headers=bearer(user)).status_code == 200

    with SessionLocal() as db:
        kit = db.scalar(select(Kit).where(Kit.kit_code == row["kit_code"]))
        assert kit.claim_code_sealed is None
        assert kit.claim_code_hmac is not None, "the code must still redeem for the same claimer"

    r = client.get("/api/kits/stickers.xlsx", headers=bearer(admin_token))
    assert r.status_code == 404, "nothing left to print"


def test_regenerating_puts_a_kit_back_on_the_sheet(client, catalog, admin_token):
    row = _batch(client, admin_token, count=1).json()["kits"][0]
    kit_id = client.get("/api/kits", headers=bearer(admin_token)).json()[0]["id"]
    fresh = client.post(f"/api/kits/{kit_id}/claim-code",
                        headers=bearer(admin_token)).json()["claim_code"]
    assert fresh != row["claim_code"]

    sheet = client.get("/api/kits/stickers.xlsx", headers=bearer(admin_token))
    codes = {c.value for r_ in load_workbook(io.BytesIO(sheet.content)).active.iter_rows()
             for c in r_}
    assert fresh in codes
    assert row["claim_code"] not in codes, "the superseded code must not be printed again"


def test_the_sheet_is_admin_only(client, catalog, user_token):
    assert client.get("/api/kits/stickers.xlsx", headers=bearer(user_token)).status_code == 403


def test_the_sheet_explains_itself_when_empty(client, catalog, admin_token):
    r = client.get("/api/kits/stickers.xlsx", headers=bearer(admin_token))
    assert r.status_code == 404
    assert "regenerat" in r.text or "fresh one" in r.text
