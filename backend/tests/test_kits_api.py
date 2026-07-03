from tests.conftest import bearer

KIT_PAYLOAD = {
    "kit_code": "DIVJA240",
    "species": "bear",
    "description": "brown bear STR panel",
    "primers": [
        {"locus": "UA_03", "type": "microsat", "primer_f": "gctc", "primer_r": "ctgg", "motif": "ctat"},
        {"locus": "ZF1L", "type": "snp", "primer_f": "gagc", "primer_r": "ggca", "sequence": "X:ACGT/Y:ACGA"},
    ],
    "tag_columns": [{"name": f"PP{i}", "ordinal": i} for i in range(1, 9)],
    "controls": [{"name_pattern": "blank", "kind": "negative"}],
}


def test_admin_can_create_kit_and_user_can_list(client, admin_token, user_token):
    # admin creates
    r = client.post("/api/kits", json=KIT_PAYLOAD, headers=bearer(admin_token))
    assert r.status_code == 201, r.text
    kit = r.json()
    assert kit["kit_code"] == "DIVJA240"
    assert len(kit["primers"]) == 2
    assert len(kit["tag_columns"]) == 8
    assert kit["primers"][0]["motif"] == "ctat"          # STR carries motif
    assert kit["primers"][1]["sequence"] == "X:ACGT/Y:ACGA"  # SNP carries sequence

    # duplicate kit_code rejected
    assert client.post("/api/kits", json=KIT_PAYLOAD, headers=bearer(admin_token)).status_code == 409

    # regular user can list (needs it for the submit picker) but sees the tag columns
    lst = client.get("/api/kits", headers=bearer(user_token))
    assert lst.status_code == 200
    assert lst.json()[0]["tag_columns"][0]["name"] == "PP1"


def test_regular_user_cannot_create_or_delete(client, user_token):
    assert client.post("/api/kits", json=KIT_PAYLOAD, headers=bearer(user_token)).status_code == 403


def test_get_and_delete_kit(client, admin_token):
    kit_id = client.post("/api/kits", json=KIT_PAYLOAD, headers=bearer(admin_token)).json()["id"]
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 200
    assert client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 204
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 404
