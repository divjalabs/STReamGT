import pytest

from tests.conftest import bearer

KIT = {
    "kit_code": "DIVJA240",
    "species": "bear",
    "primers": [{"locus": "UA_03", "type": "microsat", "motif": "ctat"}],
    "tag_columns": [{"name": f"PP{i}", "ordinal": i} for i in range(1, 9)],
    "controls": [{"name_pattern": "blank"}],
}


@pytest.fixture(autouse=True)
def no_enqueue(monkeypatch):
    """Don't hit Redis/Celery during API tests; record enqueued job ids instead."""
    calls = []
    monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: calls.append(job_id))
    return calls


def _make_kit(client, admin_token) -> int:
    return client.post("/api/kits", json=KIT, headers=bearer(admin_token)).json()["id"]


def job_payload(kit_id):
    return {
        "kit_id": kit_id,
        "fastq_source": "upload",
        "fastq1_ref": "uploads/1/x/reads_1.fastq.gz",
        "fastq2_ref": "uploads/1/x/reads_2.fastq.gz",
        "expected_read_number": 10_000_000,
        "batches": [
            {"name": "HRM01", "sample_sheet_key": "uploads/1/x/HRM01.xlsx",
             "selected_tags": ["PP1", "PP2", "PP3", "PP4"]},
            {"name": "HRM02", "sample_names_text": "S1\nS2\nS3",
             "selected_tags": ["PP5", "PP6", "PP7", "PP8"]},
        ],
    }


def test_create_job_enqueues_and_stores_batches(client, admin_token, user_token, no_enqueue):
    kit_id = _make_kit(client, admin_token)
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert len(job["batches"]) == 2
    assert job["batches"][0]["selected_tags"] == ["PP1", "PP2", "PP3", "PP4"]
    assert job["batches"][0]["species"] == "bear"   # inherited from kit
    assert len(no_enqueue) == 1                      # one job enqueued


def test_reject_unknown_tag_columns(client, admin_token, user_token):
    kit_id = _make_kit(client, admin_token)
    payload = job_payload(kit_id)
    payload["batches"][0]["selected_tags"] = ["PP1", "PP99"]
    r = client.post("/api/jobs", json=payload, headers=bearer(user_token))
    assert r.status_code == 422 and "PP99" in r.text


def test_batch_requires_samples(client, admin_token, user_token):
    kit_id = _make_kit(client, admin_token)
    payload = job_payload(kit_id)
    payload["batches"][0] = {"name": "bad", "selected_tags": ["PP1"]}  # no sheet, no text
    assert client.post("/api/jobs", json=payload, headers=bearer(user_token)).status_code == 422


def test_ownership_isolation(client, admin_token, user_token):
    kit_id = _make_kit(client, admin_token)
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    # a second user cannot see the first user's job
    other = client.post("/api/auth/register", json={"email": "other@x.com", "password": "otherpass1"}).json()["access_token"]
    assert client.get(f"/api/jobs/{pub}", headers=bearer(other)).status_code == 403
    # owner sees it and it appears in their list
    assert client.get(f"/api/jobs/{pub}", headers=bearer(user_token)).status_code == 200
    assert len(client.get("/api/jobs", headers=bearer(user_token)).json()) == 1
    assert client.get("/api/jobs", headers=bearer(other)).json() == []


def test_init_upload_small_uses_put(client, user_token):
    r = client.post(
        "/api/jobs/uploads",
        json={"filename": "HRM01.xlsx", "size": 1024, "purpose": "sample"},
        headers=bearer(user_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "put" and body["put_url"] and body["key"].endswith("HRM01.xlsx")
