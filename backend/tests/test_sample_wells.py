import io
import tempfile

from app.worker import pipeline_run as pr
from tests.conftest import bearer


LETTERS = "ABCDEFGH"


def _rows(n: int) -> list[dict]:
    """First n wells of a plate (A1..H1,A2..) each carrying a sample name."""
    wells = [f"{l}{num}" for num in range(1, 13) for l in LETTERS]
    return [{"TPositionId": w, "SPositionBC": f"S{i}", "control_type": ""}
            for i, w in enumerate(wells[:n])]


def _xlsx_bytes(rows: list[dict]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        pr.write_sample_xlsx(rows, tmp.name)
        with open(tmp.name, "rb") as fh:
            return fh.read()


def test_count_filled_wells_counts_named_distinct():
    assert pr.count_filled_wells(_rows(96)) == 96
    assert pr.count_filled_wells(_rows(50)) == 50
    # empty names don't count
    rows = _rows(96)
    rows[0]["SPositionBC"] = ""
    assert pr.count_filled_wells(rows) == 95
    # duplicate positions count once
    rows = _rows(10) + [{"TPositionId": "A1", "SPositionBC": "dupe", "control_type": ""}]
    assert pr.count_filled_wells(rows) == 10


def test_read_sample_xlsx_roundtrips_and_skips_header():
    path_bytes = _xlsx_bytes(_rows(96))
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        tmp.write(path_bytes)
        tmp.flush()
        out = pr.read_sample_xlsx(tmp.name)
    assert pr.count_filled_wells(out) == 96
    assert all(r["TPositionId"].lower() not in ("tpositionid", "position") for r in out)


def test_inspect_endpoint_full_plate(client, catalog, admin_token):
    data = _xlsx_bytes(_rows(96))
    r = client.post(
        "/api/jobs/sample-sheet/inspect",
        files={"file": ("plate.xlsx", io.BytesIO(data),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=bearer(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"wells": 96, "total": 96}


def test_inspect_endpoint_partial_plate(client, catalog, admin_token):
    data = _xlsx_bytes(_rows(72))
    r = client.post(
        "/api/jobs/sample-sheet/inspect",
        files={"file": ("plate.xlsx", io.BytesIO(data), "application/octet-stream")},
        headers=bearer(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["wells"] == 72


def test_inspect_endpoint_rejects_non_xlsx(client, catalog, admin_token):
    r = client.post(
        "/api/jobs/sample-sheet/inspect",
        files={"file": ("notes.txt", io.BytesIO(b"not a spreadsheet"), "text/plain")},
        headers=bearer(admin_token),
    )
    assert r.status_code == 422


def test_inspect_endpoint_requires_auth(client, catalog):
    r = client.post(
        "/api/jobs/sample-sheet/inspect",
        files={"file": ("plate.xlsx", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert r.status_code == 401
