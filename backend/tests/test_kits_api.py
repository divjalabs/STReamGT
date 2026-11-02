import pytest
from sqlalchemy import select

from app.db import SessionLocal
from tests.conftest import bearer, register, user_id, panel_id


def _register_kit(client, admin_token, assigned_ids, code="DIVJA240"):
    """Register a kit and grant `assigned_ids` access to it.

    Two calls, because registration no longer takes an assignee list — in production access comes
    from redeeming the claim code, and an admin grant is a separate PATCH.
    """
    payload = {
        "kit_code": code,
        "panel_id": panel_id("UA_primers"),
        "selected_tags": ["PP1", "PP2", "PP3", "PP4"],
    }
    r = client.post("/api/kits", json=payload, headers=bearer(admin_token))
    if r.status_code == 201 and assigned_ids:
        client.patch(
            f"/api/kits/{r.json()['id']}",
            json={"assigned_user_ids": assigned_ids},
            headers=bearer(admin_token),
        )
    return r


def test_admin_registers_kit_from_panel(client, catalog, admin_token):
    r = client.post(
        "/api/kits",
        json={
            "kit_code": "DIVJA240",
            "panel_id": panel_id("UA_primers"),
            "selected_tags": ["PP1", "PP2", "PP3", "PP4"],
        },
        headers=bearer(admin_token),
    )
    assert r.status_code == 201, r.text
    kit = r.json()
    assert kit["species"] == "brown bear"          # denormalized from the panel
    assert kit["status"] == "sent"                 # default
    assert [t["name"] for t in kit["tag_columns"]] == ["PP1", "PP2", "PP3", "PP4"]
    assert kit["controls"][0]["name_pattern"] == "blank"  # default control
    assert kit["panel"]["code"] == "UA_primers"


def test_position_controls_autoname_and_validate(client, catalog, admin_token):
    r = client.post(
        "/api/kits",
        json={
            "kit_code": "DIVJA300",
            "panel_id": panel_id("UA_primers"),
            "selected_tags": ["PP1", "PP2"],
            "controls": [
                {"kind": "sequencing", "name_pattern": "blank"},   # legacy pattern row
                {"kind": "pcr", "position": "a1"},                 # auto-named, lowercased well
                {"kind": "sequencing", "position": "b1"},          # token 'blank', not 'sequencing'
                {"kind": "extraction", "position": "c1"},          # token 'ext'
                {"kind": "positive", "position": "H12", "name": "myPos"},
            ],
        },
        headers=bearer(admin_token),
    )
    assert r.status_code == 201, r.text
    controls = r.json()["controls"]
    by_pos = {c["position"]: c for c in controls if c["position"]}
    assert by_pos["A1"]["name"] == "DIVJA300_pcr_A1"       # auto-generated
    assert by_pos["B1"]["name"] == "DIVJA300_blank_B1"     # sequencing -> 'blank' token
    assert by_pos["C1"]["name"] == "DIVJA300_ext_C1"       # extraction -> 'ext' token
    assert by_pos["H12"]["name"] == "myPos"                # explicit kept
    # KitSummary (list) also carries controls
    summary = [k for k in client.get("/api/kits", headers=bearer(admin_token)).json()
               if k["kit_code"] == "DIVJA300"][0]
    assert {c["kind"] for c in summary["controls"] if c["position"]} == \
        {"pcr", "sequencing", "extraction", "positive"}


def test_download_control_template(client, catalog, admin_token):
    import io
    from openpyxl import load_workbook
    r = client.post(
        "/api/kits",
        json={"kit_code": "DIVJA310", "panel_id": panel_id("UA_primers"), "selected_tags": ["PP1"],
              "controls": [{"kind": "pcr", "position": "B1"}]},
        headers=bearer(admin_token),
    )
    kit_id = r.json()["id"]
    resp = client.get(f"/api/kits/{kit_id}/control-template.xlsx", headers=bearer(admin_token))
    assert resp.status_code == 200
    assert "spreadsheet" in resp.headers["content-type"]
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    assert [ws.cell(1, c).value for c in (1, 2, 3)] == ["Position", "Sample Name", "Control type"]
    # the pcr control at B1 is pre-filled with its name + type
    filled = {ws.cell(row, 1).value: (ws.cell(row, 2).value, ws.cell(row, 3).value)
              for row in range(2, 98) if ws.cell(row, 2).value}
    assert filled["B1"] == ("DIVJA310_pcr_B1", "pcr")


def test_duplicate_control_well_rejected(client, catalog, admin_token):
    r = client.post(
        "/api/kits",
        json={
            "kit_code": "DIVJA301", "panel_id": panel_id("UA_primers"),
            "selected_tags": ["PP1"],
            "controls": [{"kind": "pcr", "position": "A1"}, {"kind": "positive", "position": "A1"}],
        },
        headers=bearer(admin_token),
    )
    assert r.status_code == 422 and "A1" in r.text


def test_control_templates_crud(client, catalog, admin_token, user_token):
    body = {"name": "std-layout", "positions": [
        {"kind": "pcr", "position": "A1"}, {"kind": "sequencing", "position": "B1"}]}
    r = client.post("/api/control-templates", json=body, headers=bearer(admin_token))
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert len(r.json()["positions"]) == 2
    # non-admin forbidden
    assert client.post("/api/control-templates", json=body, headers=bearer(user_token)).status_code == 403
    # duplicate name rejected
    assert client.post("/api/control-templates", json=body, headers=bearer(admin_token)).status_code == 409
    assert any(t["id"] == tid for t in client.get("/api/control-templates", headers=bearer(admin_token)).json())
    assert client.delete(f"/api/control-templates/{tid}", headers=bearer(admin_token)).status_code == 204


def test_unknown_tag_columns_rejected(client, catalog, admin_token):
    r = client.post(
        "/api/kits",
        json={"kit_code": "K1", "panel_id": panel_id(), "selected_tags": ["PP1", "PP99"]},
        headers=bearer(admin_token),
    )
    assert r.status_code == 422 and "PP99" in r.text


def test_kit_reads_crud(client, catalog, admin_token, user_token, monkeypatch):
    monkeypatch.setattr("app.api.kits.storage.object_exists", lambda key: True)
    tok_a = register(client, "a@x.com")
    tok_b = register(client, "b@x.com")
    kit_id = _register_kit(client, admin_token, [user_id("a@x.com")]).json()["id"]
    k1 = f"reads/kit/{kit_id}/u/reads_1.fastq.gz"
    k2 = f"reads/kit/{kit_id}/u/reads_2.fastq.gz"
    body = {"fastq1_key": k1, "fastq2_key": k2, "fastq1_name": "r1", "fastq2_name": "r2",
            "size1": 10, "size2": 20}

    # assigned user can register; outsider cannot
    assert client.put(f"/api/kits/{kit_id}/reads", json=body, headers=bearer(tok_b)).status_code == 403
    r = client.put(f"/api/kits/{kit_id}/reads", json=body, headers=bearer(tok_a))
    assert r.status_code == 200 and r.json()["fastq1_key"] == k1
    assert client.get(f"/api/kits/{kit_id}/reads", headers=bearer(tok_a)).json()["fastq2_name"] == "r2"

    # keys outside the kit's prefix are rejected
    bad = {**body, "fastq1_key": "uploads/9/x/evil.gz"}
    assert client.put(f"/api/kits/{kit_id}/reads", json=bad, headers=bearer(tok_a)).status_code == 422

    # delete clears it
    assert client.delete(f"/api/kits/{kit_id}/reads", headers=bearer(tok_a)).status_code == 204
    assert client.get(f"/api/kits/{kit_id}/reads", headers=bearer(tok_a)).json() is None


def test_kit_claim_flow(client, catalog, admin_token):
    tok = register(client, "buyer@x.com")
    kit = _register_kit(client, admin_token, [], code="CLAIMKIT").json()   # assigned to nobody
    code = kit["claim_code"]
    assert code and "-" in code
    assert client.get("/api/kits", headers=bearer(tok)).json() == []       # inert until claimed
    # wrong code -> 404
    assert client.post("/api/kits/claim", json={"code": "WRON-GWRO-NGWR-ONGW"},
                       headers=bearer(tok)).status_code == 404
    # claim -> visible to the buyer
    assert client.post("/api/kits/claim", json={"code": code}, headers=bearer(tok)).status_code == 200
    assert [k["kit_code"] for k in client.get("/api/kits", headers=bearer(tok)).json()] == ["CLAIMKIT"]
    # a second user cannot claim the same kit
    tok2 = register(client, "other@x.com")
    assert client.post("/api/kits/claim", json={"code": code}, headers=bearer(tok2)).status_code == 409
    # admin sees every kit + who claimed it
    adm = next(k for k in client.get("/api/kits", headers=bearer(admin_token)).json()
               if k["kit_code"] == "CLAIMKIT")
    assert adm["claimed_by_email"] == "buyer@x.com"


def test_claim_code_never_stored_plaintext(client, catalog, admin_token):
    from app.db import SessionLocal
    from app.models import Kit
    from sqlalchemy import select
    kit = _register_kit(client, admin_token, [], code="HASHONLY").json()
    with SessionLocal() as db:
        row = db.scalar(select(Kit).where(Kit.kit_code == "HASHONLY"))
        assert row.claim_code_hmac and len(row.claim_code_hmac) == 64
        assert kit["claim_code"] not in row.claim_code_hmac      # only the hmac is persisted


def test_regenerate_and_revoke(client, catalog, admin_token):
    tok = register(client, "buyer@x.com")
    kit = _register_kit(client, admin_token, [], code="REGEN").json()
    kid, old = kit["id"], kit["claim_code"]
    new = client.post(f"/api/kits/{kid}/claim-code", headers=bearer(admin_token)).json()["claim_code"]
    assert new != old
    assert client.post("/api/kits/claim", json={"code": old}, headers=bearer(tok)).status_code == 404
    assert client.post("/api/kits/claim", json={"code": new}, headers=bearer(tok)).status_code == 200
    # admin revoke detaches the claimer
    assert client.delete(f"/api/kits/{kid}/claim", headers=bearer(admin_token)).status_code == 200
    assert client.get("/api/kits", headers=bearer(tok)).json() == []


def test_signing_up_no_longer_takes_a_kit_code(client, catalog, admin_token):
    """There is one way into a kit now: redeem the code from My kits once you are logged in.

    A stray claim_code in the body must be ignored rather than honoured — not rejected either,
    so an old client or script does not start failing at sign-up.
    """
    code = _register_kit(client, admin_token, [], code="ONBOARD").json()["claim_code"]
    r = client.post("/api/auth/register",
                    json={"email": "new@x.com", "password": "password123", "claim_code": code})
    assert r.status_code == 201
    tok = r.json()["access_token"]
    assert client.get("/api/kits", headers=bearer(tok)).json() == []

    # ...and the code is untouched, so it still works from the kits page.
    assert client.post("/api/kits/claim", json={"code": code}, headers=bearer(tok)).status_code == 200
    assert [k["kit_code"] for k in client.get("/api/kits", headers=bearer(tok)).json()] == ["ONBOARD"]

    # A nonsense code no longer costs anybody their account: sign-up does not look at it.
    bad = client.post("/api/auth/register",
                      json={"email": "nope@x.com", "password": "password123", "claim_code": "BADX-BADX-BADX-BADX"})
    assert bad.status_code == 201
    assert client.post("/api/auth/login",
                       data={"username": "nope@x.com", "password": "password123"}).status_code == 200


def test_access_control(client, catalog, admin_token):
    tok_a = register(client, "a@x.com")
    tok_b = register(client, "b@x.com")
    # kit assigned only to user A
    r = _register_kit(client, admin_token, [user_id("a@x.com")])
    assert r.status_code == 201
    kit_id = r.json()["id"]

    # A sees it; B does not; admin sees it
    assert [k["kit_code"] for k in client.get("/api/kits", headers=bearer(tok_a)).json()] == ["DIVJA240"]
    assert client.get("/api/kits", headers=bearer(tok_b)).json() == []
    assert len(client.get("/api/kits", headers=bearer(admin_token)).json()) == 1

    # direct get: A ok, B forbidden
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(tok_a)).status_code == 200
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(tok_b)).status_code == 403


def test_status_transitions(client, catalog, admin_token):
    tok_a = register(client, "a@x.com")
    kit_id = _register_kit(client, admin_token, [user_id("a@x.com")]).json()["id"]

    # client may set received, not analysed
    assert client.patch(f"/api/kits/{kit_id}", json={"status": "received"}, headers=bearer(tok_a)).json()["status"] == "received"
    assert client.patch(f"/api/kits/{kit_id}", json={"status": "analysed"}, headers=bearer(tok_a)).status_code == 403
    # client cannot self-approve a re-analysis either
    assert client.patch(f"/api/kits/{kit_id}", json={"status": "reanalyse"}, headers=bearer(tok_a)).status_code == 403
    # admin may set anything, including reanalyse
    assert client.patch(f"/api/kits/{kit_id}", json={"status": "analysed"}, headers=bearer(admin_token)).json()["status"] == "analysed"
    assert client.patch(f"/api/kits/{kit_id}", json={"status": "reanalyse"}, headers=bearer(admin_token)).json()["status"] == "reanalyse"


def test_non_admin_cannot_create_kit(client, catalog, user_token):
    assert _register_kit(client, user_token, []).status_code == 403


def test_delete_kit(client, catalog, admin_token):
    kit_id = _register_kit(client, admin_token, []).json()["id"]
    assert client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 204
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 404


def test_delete_analysed_kit_blocked(client, catalog, admin_token):
    kit_id = _register_kit(client, admin_token, []).json()["id"]
    assert client.patch(
        f"/api/kits/{kit_id}", json={"status": "analysed"}, headers=bearer(admin_token)
    ).json()["status"] == "analysed"
    r = client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 409, r.text
    assert "analysed" in r.json()["detail"]
    # kit still there
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 200


def test_patching_status_keeps_the_description(client, catalog, admin_token):
    """A PATCH that doesn't mention the description must leave it alone.

    The admin UI used to send description="" with every status/assignee change, silently wiping
    a field it never displayed.
    """
    kit_id = _register_kit(client, admin_token, [], code="DIVJA500").json()["id"]
    r = client.patch(f"/api/kits/{kit_id}", json={"description": "Bear samples, batch 3"},
                     headers=bearer(admin_token))
    assert r.status_code == 200, r.text

    r = client.patch(f"/api/kits/{kit_id}", json={"status": "received"}, headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Bear samples, batch 3"

    # An explicit empty string still clears it.
    r = client.patch(f"/api/kits/{kit_id}", json={"description": ""}, headers=bearer(admin_token))
    assert r.status_code == 200 and r.json()["description"] == ""


def test_kit_list_exposes_description(client, catalog, admin_token):
    """So a lost description would be visible in the admin table rather than invisible."""
    kit_id = _register_kit(client, admin_token, [], code="DIVJA501").json()["id"]
    client.patch(f"/api/kits/{kit_id}", json={"description": "Wolf, 2026"}, headers=bearer(admin_token))
    kits = client.get("/api/kits", headers=bearer(admin_token)).json()
    assert next(k for k in kits if k["id"] == kit_id)["description"] == "Wolf, 2026"


# ---------- the per-kit analysis setup ----------
# The sheet a user fills in before the sequencing comes back. It must accept an INCOMPLETE sheet:
# everything POST /jobs insists on (tags belonging to the kit, a batch, 96 filled wells) is
# checked at submission, not here, or there would be nothing to save on a Tuesday afternoon.

def _plate_text(n=3):
    return "\n".join(f"A{i},SAMPLE{i}," for i in range(1, n + 1))


def test_a_setup_round_trips_including_the_plate(client, catalog, admin_token):
    kit_id = _register_kit(client, admin_token, [], code="SETUP1").json()["id"]
    assert client.get(f"/api/kits/{kit_id}/analysis-setup",
                      headers=bearer(admin_token)).json() is None

    body = {
        "expected_read_number": 12345678,
        "parameters": {"negative_name": "blank", "discard_threshold": 7},
        "batches": [{"name": "HRM01", "selected_tags": ["PP1", "PP2"],
                     "sample_names_text": _plate_text(4)}],
    }
    r = client.put(f"/api/kits/{kit_id}/analysis-setup", json=body, headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["updated_by_email"] == "admin@x.com"

    got = client.get(f"/api/kits/{kit_id}/analysis-setup", headers=bearer(admin_token)).json()
    assert got["expected_read_number"] == 12345678
    assert got["parameters"]["discard_threshold"] == 7
    assert got["batches"][0]["name"] == "HRM01"
    assert got["batches"][0]["selected_tags"] == ["PP1", "PP2"]
    # the part that actually hurts to retype
    assert got["batches"][0]["sample_names_text"] == _plate_text(4)


def test_a_half_finished_sheet_saves(client, catalog, admin_token):
    kit_id = _register_kit(client, admin_token, [], code="SETUP2").json()["id"]
    for body in (
        {},                                                        # nothing at all
        {"batches": []},                                           # no batches
        {"batches": [{"name": None, "selected_tags": []}]},        # a batch with nothing in it
        {"batches": [{"name": "x", "selected_tags": ["PP9"],       # a tag the kit doesn't have
                      "sample_names_text": _plate_text(1)}]},      # and 1 well, not 96
    ):
        r = client.put(f"/api/kits/{kit_id}/analysis-setup", json=body, headers=bearer(admin_token))
        assert r.status_code == 200, f"{body} -> {r.text}"


def test_saving_twice_updates_one_row(client, catalog, admin_token):
    kit_id = _register_kit(client, admin_token, [], code="SETUP3").json()["id"]
    for n in (1, 2, 3):
        client.put(f"/api/kits/{kit_id}/analysis-setup",
                   json={"expected_read_number": n}, headers=bearer(admin_token))
    with SessionLocal() as db:
        from app.models import KitAnalysisSetup
        rows = db.scalars(select(KitAnalysisSetup).where(
            KitAnalysisSetup.kit_id == kit_id)).all()
    assert len(rows) == 1 and rows[0].expected_read_number == 3


def test_the_setup_follows_the_same_access_rule_as_the_kit(client, catalog, admin_token):
    tok = register(client, "outsider@x.com")
    kit_id = _register_kit(client, admin_token, [], code="SETUP4").json()["id"]
    assert client.get(f"/api/kits/{kit_id}/analysis-setup", headers=bearer(tok)).status_code == 403
    assert client.put(f"/api/kits/{kit_id}/analysis-setup", json={},
                      headers=bearer(tok)).status_code == 403


def test_deleting_the_kit_takes_its_setup_with_it(client, catalog, admin_token):
    kit_id = _register_kit(client, admin_token, [], code="SETUP5").json()["id"]
    client.put(f"/api/kits/{kit_id}/analysis-setup", json={"expected_read_number": 1},
               headers=bearer(admin_token))
    assert client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 204
    with SessionLocal() as db:
        from app.models import KitAnalysisSetup
        assert db.scalars(select(KitAnalysisSetup).where(
            KitAnalysisSetup.kit_id == kit_id)).all() == []


# ---------- downloading a kit's reads ----------
# Until this existed, an upload was write-only: presign_get was reachable only for results, the
# tag layout and panel CSVs, so nobody could check what they had sent.

@pytest.fixture()
def s3_bucket():
    """Real presigning against moto, so these exercise the same code path as production."""
    import boto3
    from moto import mock_aws
    from app.config import settings
    from app.services import storage

    with mock_aws():
        storage._client.cache_clear()
        boto3.client("s3", region_name=settings.s3_region).create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.s3_region},
        )
        yield
        storage._client.cache_clear()


READ_BODY = b"@r1\nACGT\n+\n!!!!\n"


def _kit_with_reads(client, admin_token, tok, email, code, body=READ_BODY):
    from app.services import storage
    kit_id = _register_kit(client, admin_token, [user_id(email)], code=code).json()["id"]
    keys = [f"reads/kit/{kit_id}/u/{code}_1.fastq.gz", f"reads/kit/{kit_id}/u/{code}_2.fastq.gz"]
    for k in keys:
        storage.put_bytes(k, body)
    r = client.put(f"/api/kits/{kit_id}/reads", headers=bearer(tok), json={
        "fastq1_key": keys[0], "fastq2_key": keys[1],
        "fastq1_name": f"{code}_1.fastq.gz", "fastq2_name": f"{code}_2.fastq.gz",
    })
    assert r.status_code == 200, r.text
    return kit_id, keys


def test_reads_can_be_downloaded_by_anyone_with_the_kit(client, catalog, admin_token, s3_bucket):
    tok = register(client, "owner@x.com")
    kit_id, _ = _kit_with_reads(client, admin_token, tok, "owner@x.com", "DL1")

    r = client.get(f"/api/kits/{kit_id}/reads/download", headers=bearer(tok))
    assert r.status_code == 200, r.text
    pair = r.json()
    assert [p["filename"] for p in pair] == ["DL1_1.fastq.gz", "DL1_2.fastq.gz"]
    # the size is read from S3, not from kit_reads — which this PUT deliberately left unset
    assert all(p["size_bytes"] == len(READ_BODY) for p in pair), pair
    # a presigned GET, with the filename pushed into the download disposition
    assert all("X-Amz-Signature" in p["url"] for p in pair)
    assert "DL1_1.fastq.gz" in pair[0]["url"]


def test_reads_download_is_refused_without_kit_access(client, catalog, admin_token, s3_bucket):
    tok = register(client, "holder@x.com")
    other = register(client, "nosy@x.com")
    kit_id, _ = _kit_with_reads(client, admin_token, tok, "holder@x.com", "DL2")
    assert client.get(f"/api/kits/{kit_id}/reads/download",
                      headers=bearer(other)).status_code == 403


def test_reads_download_says_so_when_there_is_nothing(client, catalog, admin_token, s3_bucket):
    kit_id = _register_kit(client, admin_token, [], code="DL3").json()["id"]
    r = client.get(f"/api/kits/{kit_id}/reads/download", headers=bearer(admin_token))
    assert r.status_code == 404 and "no reads" in r.json()["detail"].lower()


def test_reads_download_reports_a_vanished_object_rather_than_a_dead_link(
    client, catalog, admin_token, s3_bucket
):
    """A presigned URL to a deleted object 404s at S3, long after the user clicked it."""
    from app.services import storage
    tok = register(client, "gone@x.com")
    kit_id, keys = _kit_with_reads(client, admin_token, tok, "gone@x.com", "DL4")
    storage.delete_object(keys[1])

    r = client.get(f"/api/kits/{kit_id}/reads/download", headers=bearer(tok))
    assert r.status_code == 410 and "no longer" in r.json()["detail"]
