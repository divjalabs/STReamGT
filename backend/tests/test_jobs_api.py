import pytest

from tests.conftest import bearer, register, user_id, panel_id


@pytest.fixture(autouse=True)
def no_enqueue(monkeypatch):
    """Don't hit Redis/Celery/ECS during API tests; record enqueued job ids instead."""
    calls = []
    monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: calls.append(job_id))
    return calls


def _make_kit(client, admin_token, assigned_ids, code="DIVJA240") -> int:
    return client.post(
        "/api/kits",
        json={
            "kit_code": code, "panel_id": panel_id("UA_primers"),
            "selected_tags": ["PP1", "PP2", "PP3", "PP4", "PP5", "PP6", "PP7", "PP8"],
            "assigned_user_ids": assigned_ids,
        },
        headers=bearer(admin_token),
    ).json()["id"]


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


def test_create_job_requires_kit_access(client, catalog, admin_token, user_token):
    """A user without access to the kit cannot submit a job for it."""
    kit_id = _make_kit(client, admin_token, assigned_ids=[])  # assigned to nobody
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 403 and "access" in r.text.lower()


def test_create_job_enqueues_when_granted(client, catalog, admin_token, user_token, no_enqueue):
    kit_id = _make_kit(client, admin_token, assigned_ids=[user_id("user@x.com")])
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "queued" and len(job["batches"]) == 2
    assert len(no_enqueue) == 1


def test_analysed_kit_blocks_until_reanalyse(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    # admin marks the kit analysed → user can no longer submit
    client.patch(f"/api/kits/{kit_id}", json={"status": "analysed"}, headers=bearer(admin_token))
    r = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token))
    assert r.status_code == 409 and "analysed" in r.text.lower()
    # admin re-approves → user can submit again
    ok = client.patch(f"/api/kits/{kit_id}", json={"status": "reanalyse"}, headers=bearer(admin_token))
    assert ok.status_code == 200 and ok.json()["status"] == "reanalyse"
    assert client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).status_code == 201


def test_reject_unknown_tag_columns(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    payload = job_payload(kit_id)
    payload["batches"][0]["selected_tags"] = ["PP1", "PP99"]
    assert client.post("/api/jobs", json=payload, headers=bearer(user_token)).status_code == 422


def test_batch_requires_samples(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    payload = job_payload(kit_id)
    payload["batches"][0] = {"name": "bad", "selected_tags": ["PP1"]}
    assert client.post("/api/jobs", json=payload, headers=bearer(user_token)).status_code == 422


def test_ownership_isolation(client, catalog, admin_token, user_token):
    kit_id = _make_kit(client, admin_token, [user_id("user@x.com")])
    pub = client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(user_token)).json()["public_id"]
    other = register(client, "other@x.com")
    assert client.get(f"/api/jobs/{pub}", headers=bearer(other)).status_code == 403
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
