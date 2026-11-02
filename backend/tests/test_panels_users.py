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
        "kit_code": "K1", "panel_id": pid, "selected_tags": ["PP1"],
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


def test_upload_tag_layout(client, catalog, admin_token, user_token):
    with mock_aws():
        storage._client.cache_clear()
        boto3.client("s3", region_name=settings.s3_region).create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.s3_region},
        )
        csv = b"Position,PP1,PP2,PP3\n1,aaa,ttt,ccc\n2,ggg,ccc,aaa\n"
        r = client.post("/api/kits/tag-layout",
                        files={"tags_csv": ("tags.csv", csv, "text/csv")},
                        headers=bearer(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["column_names"] == ["PP1", "PP2", "PP3"]
        assert r.json()["tags_csv_key"] == "tags/tags.csv"
        # reflected by GET, and downloadable
        assert client.get("/api/kits/tag-layout", headers=bearer(admin_token)
                          ).json()["column_names"] == ["PP1", "PP2", "PP3"]
        assert "url" in client.get("/api/kits/tag-layout/download", headers=bearer(admin_token)).json()
        # a header with no PP columns -> 422; non-admin -> 403
        assert client.post("/api/kits/tag-layout",
                           files={"tags_csv": ("t.csv", b"Position\n1\n", "text/csv")},
                           headers=bearer(admin_token)).status_code == 422
        assert client.post("/api/kits/tag-layout",
                           files={"tags_csv": ("t.csv", csv, "text/csv")},
                           headers=bearer(user_token)).status_code == 403
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


# ---------- deleting a user ----------
# The database is what makes this safe: of the eleven FKs pointing at users.id, only kit_access
# and project_access cascade. Everything else is ON DELETE NO ACTION, so Postgres refuses rather
# than orphaning a genotyping run. These tests exist mostly to keep it that way — the assertions
# that the dependent row SURVIVES a refused delete are the ones that would catch somebody
# "fixing" a failed delete by adding ondelete="CASCADE".

def test_an_empty_account_can_be_deleted(client, admin_token):
    register(client, "nothing@x.com")
    uid = user_id("nothing@x.com")
    assert client.delete(f"/api/users/{uid}", headers=bearer(admin_token)).status_code == 204
    emails = {u["email"] for u in client.get("/api/users", headers=bearer(admin_token)).json()}
    assert "nothing@x.com" not in emails


def test_an_account_that_ran_an_analysis_is_refused_and_keeps_its_jobs(
    client, catalog, admin_token, monkeypatch
):
    """The important one: a refusal must leave both the user and the analysis intact."""
    from tests.test_jobs_api import _make_kit, job_payload

    # test_jobs_api has an autouse fixture for this; it does not reach across modules.
    monkeypatch.setattr("app.api.jobs.enqueue_job", lambda job_id: None)

    tok = register(client, "worker@x.com")
    uid = user_id("worker@x.com")
    kit_id = _make_kit(client, admin_token, [uid], code="DELUSER1")
    assert client.post("/api/jobs", json=job_payload(kit_id), headers=bearer(tok)).status_code == 201

    r = client.delete(f"/api/users/{uid}", headers=bearer(admin_token))
    assert r.status_code == 409
    assert "1 analysis" in r.json()["detail"]
    assert "Deactivate" in r.json()["detail"]

    # nothing was destroyed on the way out
    emails = {u["email"] for u in client.get("/api/users", headers=bearer(admin_token)).json()}
    assert "worker@x.com" in emails
    assert len(client.get("/api/jobs", headers=bearer(tok)).json()) == 1


def test_an_account_that_claimed_a_kit_is_refused_and_keeps_the_kit(client, catalog, admin_token):
    from tests.test_kits_api import _register_kit

    tok = register(client, "claimer@x.com")
    uid = user_id("claimer@x.com")
    code = _register_kit(client, admin_token, [], code="DELUSER2").json()["claim_code"]
    assert client.post("/api/kits/claim", json={"code": code}, headers=bearer(tok)).status_code == 200

    r = client.delete(f"/api/users/{uid}", headers=bearer(admin_token))
    assert r.status_code == 409 and "1 claimed kit" in r.json()["detail"]
    # the kit is still there and still claimed
    kits = client.get("/api/kits", headers=bearer(admin_token)).json()
    mine = [k for k in kits if k["kit_code"] == "DELUSER2"][0]
    assert mine["claimed_by_email"] == "claimer@x.com"


def test_a_bare_kit_grant_does_not_block_the_delete(client, catalog, admin_token):
    """kit_access cascades on purpose: a grant with no claim behind it should go with the account,
    and the kit itself must be untouched."""
    from tests.test_kits_api import _register_kit

    register(client, "granted@x.com")
    uid = user_id("granted@x.com")
    kit_id = _register_kit(client, admin_token, [uid], code="DELUSER3").json()["id"]

    assert client.delete(f"/api/users/{uid}", headers=bearer(admin_token)).status_code == 204
    kit = client.get(f"/api/kits/{kit_id}", headers=bearer(admin_token)).json()
    assert kit["kit_code"] == "DELUSER3"
    assert kit["assigned_user_ids"] == []      # the grant went with the account


def test_you_cannot_delete_yourself_or_the_last_admin(client, admin_token):
    aid = user_id("admin@x.com")
    r = client.delete(f"/api/users/{aid}", headers=bearer(admin_token))
    assert r.status_code == 400 and "your own account" in r.json()["detail"]

    # and not via another admin either, while they are the only one left
    register(client, "second@x.com")
    sid = user_id("second@x.com")
    client.patch(f"/api/users/{sid}", json={"role": "admin"}, headers=bearer(admin_token))
    stok = client.post("/api/auth/login",
                       data={"username": "second@x.com", "password": "clientpass123"}).json()["access_token"]
    # two admins now, so removing the first is allowed
    assert client.delete(f"/api/users/{aid}", headers=bearer(stok)).status_code == 204
    # ...which leaves `second` alone, and unremovable
    r = client.delete(f"/api/users/{sid}", headers=bearer(stok))
    assert r.status_code == 400      # it is also their own account


def test_the_last_admin_cannot_be_demoted_or_deactivated(client, admin_token):
    """Previously possible through the API: the UI only hid the buttons."""
    register(client, "helper@x.com")
    hid = user_id("helper@x.com")
    client.patch(f"/api/users/{hid}", json={"role": "admin"}, headers=bearer(admin_token))
    htok = client.post("/api/auth/login",
                       data={"username": "helper@x.com", "password": "clientpass123"}).json()["access_token"]
    aid = user_id("admin@x.com")

    # helper demotes the original admin — fine, helper is still an admin
    assert client.patch(f"/api/users/{aid}", json={"role": "user"},
                        headers=bearer(htok)).status_code == 200
    # now helper is the only one: they may not deactivate themselves...
    r = client.patch(f"/api/users/{hid}", json={"is_active": False}, headers=bearer(htok))
    assert r.status_code == 400 and "deactivate your own" in r.json()["detail"]
    # ...and the original admin (now a plain user) cannot demote them either
    atok = client.post("/api/auth/login",
                       data={"username": "admin@x.com", "password": "adminpass123"}).json()["access_token"]
    assert client.patch(f"/api/users/{hid}", json={"role": "user"},
                        headers=bearer(atok)).status_code == 403   # no longer an admin


def test_deleting_a_user_is_admin_only(client, user_token, admin_token):
    register(client, "victim@x.com")
    uid = user_id("victim@x.com")
    assert client.delete(f"/api/users/{uid}", headers=bearer(user_token)).status_code == 403


def test_the_schema_still_refuses_to_cascade_a_user_away():
    """A guard on the guard: if anyone sets ondelete='CASCADE' on these, deleting a client would
    erase their analyses. Asserted against the models, which the migrations are tested to match."""
    from app.models import Job, Project

    for column in (Job.__table__.c.user_id, Project.__table__.c.owner_user_id):
        fk = next(iter(column.foreign_keys))
        assert fk.ondelete is None, (
            f"{column} must not cascade from users: deleting an account would take the "
            f"genotyping records with it"
        )
        assert not column.nullable, f"{column} must stay NOT NULL"
