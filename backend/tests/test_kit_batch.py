"""Registering a consignment of kits in one go, and the sheet the lab prints stickers from.

The claim codes in that sheet exist only in the response that creates the kits — only hashes are
stored — so these tests care as much about the codes reaching the caller intact as about the rows
landing in the database.
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


def test_an_over_long_panel_name_is_refused_with_advice(client, catalog, admin_token):
    """The code prefixes every control well, so it cannot grow without limit."""
    pid = panel_id("UA_primers")
    client.patch(f"/api/panels/{pid}", json={"code": "X" * 60}, headers=bearer(admin_token))

    r = client.post(
        "/api/kits/batch",
        json={"panel_id": pid, "count": 1, "selected_tags": ["PP1"]},
        headers=bearer(admin_token),
    )
    assert r.status_code == 422
    assert "shorter name" in r.json()["detail"]


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
