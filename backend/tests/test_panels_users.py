import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.services import storage
from tests.conftest import bearer, register, user_id, panel_id


# ---------- panels ----------

def test_list_panels_admin_only(client, catalog, admin_token, user_token):
    r = client.get("/api/panels", headers=bearer(admin_token))
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()}
    assert "UA_primers" in codes and len(codes) == 11
    # non-admin forbidden
    assert client.get("/api/panels", headers=bearer(user_token)).status_code == 403


def test_get_panel_has_primers(client, catalog, admin_token):
    r = client.get(f"/api/panels/{panel_id('UA_primers')}", headers=bearer(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["species_common"] == "brown bear"
    assert len(body["primers"]) == 13 and body["primers"][0]["locus"]


def test_rename_panel(client, catalog, admin_token):
    pid = panel_id("UA_primers")
    r = client.patch(f"/api/panels/{pid}", json={"species_common": "grizzly"}, headers=bearer(admin_token))
    assert r.status_code == 200 and r.json()["species_common"] == "grizzly"


def test_delete_panel_blocked_when_in_use(client, catalog, admin_token):
    pid = panel_id("UA_primers")
    # register a kit that uses the panel
    client.post("/api/kits", json={
        "kit_code": "K1", "panel_id": pid, "selected_tags": ["PP1"], "assigned_user_ids": [],
    }, headers=bearer(admin_token))
    r = client.delete(f"/api/panels/{pid}", headers=bearer(admin_token))
    assert r.status_code == 409 and "used by kit" in r.text
    # an unused panel deletes fine
    other = panel_id("TuTr_primers")
    assert client.delete(f"/api/panels/{other}", headers=bearer(admin_token)).status_code == 204


def test_tag_layout_endpoint(client, catalog, admin_token):
    r = client.get("/api/kits/tag-layout", headers=bearer(admin_token))
    assert r.status_code == 200
    assert r.json()["column_names"][:2] == ["PP1", "PP2"]


def test_create_panel_uploads_csv(client, admin_token):
    with mock_aws():
        storage._client.cache_clear()
        boto3.client("s3", region_name=settings.s3_region).create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.s3_region},
        )
        csv = b"locus,primerF,primerR,type,motif\nX1,aaa,ttt,microsat,ACGT\n"
        r = client.post(
            "/api/panels",
            data={"code": "NEW_panel", "species_common": "test sp"},
            files={"primers_csv": ("p.csv", csv, "text/csv")},
            headers=bearer(admin_token),
        )
        assert r.status_code == 201, r.text
        assert r.json()["primers"][0]["locus"] == "X1"
        assert storage.object_exists("panels/NEW_panel.csv")
        storage._client.cache_clear()


# ---------- users ----------

def test_users_list_and_promote(client, admin_token):
    register(client, "client@x.com")
    users = client.get("/api/users", headers=bearer(admin_token)).json()
    assert {u["email"] for u in users} >= {"admin@x.com", "client@x.com"}

    cid = user_id("client@x.com")
    r = client.patch(f"/api/users/{cid}", json={"role": "admin"}, headers=bearer(admin_token))
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_admin_cannot_change_own_role(client, admin_token):
    aid = user_id("admin@x.com")
    r = client.patch(f"/api/users/{aid}", json={"role": "user"}, headers=bearer(admin_token))
    assert r.status_code == 400


def test_users_admin_only(client, user_token):
    assert client.get("/api/users", headers=bearer(user_token)).status_code == 403
