from tests.conftest import bearer, register, user_id, panel_id


def _register_kit(client, admin_token, assigned_ids, code="DIVJA240"):
    payload = {
        "kit_code": code,
        "panel_id": panel_id("UA_primers"),
        "selected_tags": ["PP1", "PP2", "PP3", "PP4"],
        "assigned_user_ids": assigned_ids,
    }
    return client.post("/api/kits", json=payload, headers=bearer(admin_token))


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


def test_unknown_tag_columns_rejected(client, catalog, admin_token):
    r = client.post(
        "/api/kits",
        json={"kit_code": "K1", "panel_id": panel_id(), "selected_tags": ["PP1", "PP99"]},
        headers=bearer(admin_token),
    )
    assert r.status_code == 422 and "PP99" in r.text


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
