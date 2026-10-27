"""One species per project: inferred-on-first-kit, and mismatch blocked at attach + submit."""
from tests.conftest import bearer, user_id
from tests.test_jobs_api import _make_kit, job_payload, no_enqueue  # noqa: F401


def _project(client, token, species=None):
    body = {"name": f"P-{species or 'none'}"}
    if species:
        body["species"] = species
    pid = client.post("/api/projects", json=body, headers=bearer(token)).json()["id"]
    pop = client.post(f"/api/projects/{pid}/populations", json={"name": "Pop"},
                      headers=bearer(token)).json()["id"]
    sid = client.post(f"/api/projects/{pid}/studies", json={"name": "S", "population_id": pop},
                      headers=bearer(token)).json()["id"]
    return pid, pop, sid


def test_attach_kit_infers_species_when_empty(client, catalog, admin_token):
    pid, _pop, sid = _project(client, admin_token)                 # no species yet
    kit_id = _make_kit(client, admin_token, assigned_ids=[])       # UA panel -> brown bear
    r = client.post(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    assert client.get(f"/api/projects/{pid}", headers=bearer(admin_token)).json()["species"] == "brown bear"


def test_attach_kit_species_mismatch_blocked(client, catalog, admin_token):
    pid, _pop, sid = _project(client, admin_token, species="Eurasian lynx")
    kit_id = _make_kit(client, admin_token, assigned_ids=[])       # brown bear
    r = client.post(f"/api/studies/{sid}/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 422 and "one species" in r.text


def test_create_job_species_mismatch_blocked(client, catalog, admin_token, no_enqueue):
    pid, pop, sid = _project(client, admin_token, species="Eurasian lynx")
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    payload = {**job_payload(kit_id), "project_id": pid,
               "default_population_id": pop, "default_study_id": sid}
    r = client.post("/api/jobs", json=payload, headers=bearer(admin_token))
    assert r.status_code == 422 and "one species" in r.text


def test_create_job_species_match_ok(client, catalog, admin_token, no_enqueue):
    pid, pop, sid = _project(client, admin_token, species="brown bear")
    kit_id = _make_kit(client, admin_token, assigned_ids=[])
    payload = {**job_payload(kit_id), "project_id": pid,
               "default_population_id": pop, "default_study_id": sid}
    r = client.post("/api/jobs", json=payload, headers=bearer(admin_token))
    assert r.status_code == 201, r.text
