"""Deleting an analysis, and deleting a kit outright.

This is the only door in the application through which genotypes can be destroyed, so the tests
that matter most are the ones asserting that a REFUSED delete changed nothing. The suite runs on
SQLite with foreign keys unenforced, so a guard that leaned on the database would pass here and
fail in production — every check is therefore explicit, and these tests pin that.
"""
import io
import uuid

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import select, func

from app.config import settings
from app.db import SessionLocal
from app.models import (
    User, Project, Population, Job, JobStatus, FastqSource, Kit, KitReads, Sample, SampleBatch,
    ConsensusGenotype, ReferenceAllele, ReplicateObservation, ResultFile, ResultKind, MatchSubgroup,
)
from app.services import storage
from tests.conftest import bearer, register, user_id, panel_id


@pytest.fixture()
def s3_bucket():
    with mock_aws():
        storage._client.cache_clear()
        boto3.client("s3", region_name=settings.s3_region).create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.s3_region},
        )
        yield
        storage._client.cache_clear()


def _kit(client, admin_token, code, assigned=()):
    payload = {"kit_code": code, "panel_id": panel_id("UA_primers"),
               "selected_tags": ["PP1", "PP2"]}
    kit_id = client.post("/api/kits", json=payload, headers=bearer(admin_token)).json()["id"]
    if assigned:
        client.patch(f"/api/kits/{kit_id}", json={"assigned_user_ids": list(assigned)},
                     headers=bearer(admin_token))
    return kit_id


def _job(kit_id, email="admin@x.com", status=JobStatus.succeeded, with_files=True):
    """A finished analysis with a batch, result rows and objects in the bucket."""
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        kit = db.get(Kit, kit_id)
        pub = uuid.uuid4().hex
        prefix = f"results/{kit.kit_code}/{pub}"
        job = Job(public_id=pub, user_id=u.id, kit_id=kit_id, status=status,
                  fastq_source=FastqSource.upload, storage_prefix=prefix)
        db.add(job); db.flush()
        db.add(SampleBatch(job_id=job.id, ordinal=0, name="B1", selected_tags=["PP1"],
                           sample_sheet_key=f"uploads/{u.id}/{pub}/plate.xlsx"))
        if with_files:
            db.add(ResultFile(job_id=job.id, kind=ResultKind.genotypes,
                              object_key=f"{prefix}/genotypes.txt", filename="genotypes.txt"))
        db.commit()
        return job.id, pub, prefix


def _put(key, body=b"x" * 10):
    storage.put_bytes(key, body)


# ---------- deleting an analysis ----------

def test_a_superseded_analysis_deletes_with_its_files(client, catalog, admin_token, s3_bucket):
    kit_id = _kit(client, admin_token, "DELJOB1")
    job_id, pub, prefix = _job(kit_id)
    _put(f"{prefix}/genotypes.txt")
    _put(f"{prefix}/report.html")
    sheet = f"uploads/1/{pub}/plate.xlsx"
    _put(sheet)

    assert client.delete(f"/api/jobs/{pub}", headers=bearer(admin_token)).status_code == 204

    with SessionLocal() as db:
        assert db.get(Job, job_id) is None
        assert db.scalar(select(func.count()).select_from(SampleBatch)
                         .where(SampleBatch.job_id == job_id)) == 0
        assert db.scalar(select(func.count()).select_from(ResultFile)
                         .where(ResultFile.job_id == job_id)) == 0
    # the files are actually gone, not merely unreferenced
    assert not storage.object_exists(f"{prefix}/genotypes.txt")
    assert not storage.object_exists(f"{prefix}/report.html")


def test_an_analysis_that_owns_samples_is_refused_and_loses_nothing(
    client, catalog, admin_token, s3_bucket
):
    """The assertion that matters: after the refusal, the science is still there."""
    kit_id = _kit(client, admin_token, "DELJOB2")
    job_id, pub, prefix = _job(kit_id)
    _put(f"{prefix}/genotypes.txt")

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Keep", owner_user_id=u.id)
        db.add(proj); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code="S-9", project_id=proj.id,
                   kit_id=kit_id, job_id=job_id, name="w1")
        db.add(s); db.flush()
        db.add(ConsensusGenotype(sample_id=s.id, marker="M1", allele1="a"))
        db.commit()
        sid = s.id

    r = client.delete(f"/api/jobs/{pub}", headers=bearer(admin_token))
    assert r.status_code == 409
    assert "1 sample" in r.json()["detail"]

    with SessionLocal() as db:
        assert db.get(Job, job_id) is not None
        assert db.get(Sample, sid) is not None
        assert db.scalar(select(func.count()).select_from(ConsensusGenotype)
                         .where(ConsensusGenotype.sample_id == sid)) == 1
    assert storage.object_exists(f"{prefix}/genotypes.txt"), "a refusal must not touch storage"


def test_a_running_analysis_must_be_stopped_first(client, catalog, admin_token, s3_bucket):
    kit_id = _kit(client, admin_token, "DELJOB3")
    _, pub, _ = _job(kit_id, status=JobStatus.running)
    r = client.delete(f"/api/jobs/{pub}", headers=bearer(admin_token))
    assert r.status_code == 409 and "Stop it first" in r.json()["detail"]


def test_only_the_submitter_or_an_admin_can_delete_an_analysis(
    client, catalog, admin_token, s3_bucket
):
    other = register(client, "notmine@x.com")
    kit_id = _kit(client, admin_token, "DELJOB4")
    _, pub, _ = _job(kit_id)
    assert client.delete(f"/api/jobs/{pub}", headers=bearer(other)).status_code == 403


# ---------- deleting a kit that holds nothing ----------

def test_the_in_use_guard_refuses_a_kit_with_an_analysis(client, catalog, admin_token, s3_bucket):
    """This guard has existed all along with no test behind it."""
    kit_id = _kit(client, admin_token, "DELKIT1")
    _job(kit_id)
    r = client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 409 and "in use" in r.json()["detail"]
    assert client.get(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 200


def test_the_in_use_guard_refuses_a_kit_with_samples_even_when_not_analysed(
    client, catalog, admin_token, s3_bucket
):
    kit_id = _kit(client, admin_token, "DELKIT2")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="P2", owner_user_id=u.id)
        db.add(proj); db.flush()
        db.add(Sample(public_id=uuid.uuid4().hex, system_code="S-8", project_id=proj.id,
                      kit_id=kit_id, name="w"))
        db.commit()
    r = client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token))
    assert r.status_code == 409 and "in use" in r.json()["detail"]


def test_deleting_an_empty_kit_also_removes_its_fastq(client, catalog, admin_token, s3_bucket):
    """It used to delete the row holding the keys and leave the gigabytes behind."""
    kit_id = _kit(client, admin_token, "DELKIT3")
    k1 = f"reads/kit/{kit_id}/u/r1.fastq.gz"
    k2 = f"reads/kit/{kit_id}/u/r2.fastq.gz"
    _put(k1); _put(k2)
    with SessionLocal() as db:
        db.add(KitReads(kit_id=kit_id, fastq1_key=k1, fastq2_key=k2))
        db.commit()

    assert client.delete(f"/api/kits/{kit_id}", headers=bearer(admin_token)).status_code == 204
    assert not storage.object_exists(k1)
    assert not storage.object_exists(k2)


# ---------- the cascade ----------

def _kit_with_science(client, admin_token, code):
    """A kit with an analysis, samples, consensus, replicates and an animal assignment."""
    kit_id = _kit(client, admin_token, code)
    job_id, pub, prefix = _job(kit_id)
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = db.scalar(select(Project).where(Project.name == "Shared"))
        if proj is None:
            proj = Project(public_id=uuid.uuid4().hex, name="Shared", owner_user_id=u.id)
            db.add(proj); db.flush()
        pop = db.scalar(select(Population).where(Population.project_id == proj.id))
        if pop is None:
            pop = Population(project_id=proj.id, name="Pop"); db.add(pop); db.flush()
        ra = ReferenceAllele(project_id=proj.id, marker="M1", sequence=f"{code}seq",
                             allele_name="a")
        db.add(ra); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{code}", project_id=proj.id,
                   population_id=pop.id, kit_id=kit_id, job_id=job_id, name=f"{code}_w1")
        db.add(s); db.flush()
        db.add(ConsensusGenotype(sample_id=s.id, marker="M1", allele1="a", allele1_id=ra.id))
        db.add(ReplicateObservation(sample_id=s.id, marker="M1", plate=1, position=1,
                                    read_count=10, sequence="acgt"))
        sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=pop.id, label="A",
                           reference_sample_id=s.id, n_samples=1)
        db.add(sg); db.flush()
        s.subgroup_id = sg.id
        db.commit()
        return kit_id, s.id, proj.id, pub, prefix


def test_the_cascade_needs_the_kit_code_confirmed(client, catalog, admin_token, s3_bucket):
    kit_id, sid, _, _, _ = _kit_with_science(client, admin_token, "CASC0")
    for url in (f"/api/kits/{kit_id}/everything",
                f"/api/kits/{kit_id}/everything?confirm=wrong"):
        r = client.delete(url, headers=bearer(admin_token))
        assert r.status_code == 400, url
        assert "confirm" in r.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.get(Kit, kit_id) is not None
        assert db.get(Sample, sid) is not None


def test_the_cascade_removes_the_kit_and_everything_it_produced(
    client, catalog, admin_token, s3_bucket
):
    keep_kit, keep_sid, proj_id, _, _ = _kit_with_science(client, admin_token, "CASCKEEP")
    doom_kit, doom_sid, _, doom_pub, doom_prefix = _kit_with_science(client, admin_token, "CASCGO")
    _put(f"{doom_prefix}/genotypes.txt")
    _put(f"reads/kit/{doom_kit}/u/r1.fastq.gz")

    r = client.delete(f"/api/kits/{doom_kit}/everything?confirm=CASCGO",
                      headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["samples"] == 1 and body["jobs"] == 1
    assert body["objects_deleted"] >= 2

    with SessionLocal() as db:
        assert db.get(Kit, doom_kit) is None
        assert db.get(Sample, doom_sid) is None
        assert db.scalar(select(func.count()).select_from(Job)
                         .where(Job.kit_id == doom_kit)) == 0
        assert db.scalar(select(func.count()).select_from(ConsensusGenotype)
                         .where(ConsensusGenotype.sample_id == doom_sid)) == 0
        assert db.scalar(select(func.count()).select_from(ReplicateObservation)
                         .where(ReplicateObservation.sample_id == doom_sid)) == 0
        # the sibling kit in the SAME project and population is untouched...
        assert db.get(Kit, keep_kit) is not None
        assert db.get(Sample, keep_sid) is not None
        # ...and the project itself survives
        assert db.get(Project, proj_id) is not None
    assert not storage.object_exists(f"{doom_prefix}/genotypes.txt")
    assert not storage.object_exists(f"reads/kit/{doom_kit}/u/r1.fastq.gz")


def test_the_impact_report_states_what_would_go(client, catalog, admin_token, s3_bucket):
    kit_id, _, _, _, _ = _kit_with_science(client, admin_token, "CASCIMP")
    r = client.get(f"/api/kits/{kit_id}/deletion-impact", headers=bearer(admin_token))
    assert r.status_code == 200
    imp = r.json()
    assert imp["kit_code"] == "CASCIMP"
    assert imp["samples"] == 1 and imp["consensus_genotypes"] == 1
    assert imp["replicate_observations"] == 1 and imp["jobs"] == 1
    # the consequence that is easy to miss: matching is population-scoped, so it gets cleared
    assert imp["populations_whose_matching_is_cleared"] == ["Pop"]


def test_the_cascade_is_admin_only(client, catalog, admin_token, user_token, s3_bucket):
    kit_id = _kit(client, admin_token, "CASCADM")
    assert client.delete(f"/api/kits/{kit_id}/everything?confirm=CASCADM",
                         headers=bearer(user_token)).status_code == 403
    assert client.get(f"/api/kits/{kit_id}/deletion-impact",
                      headers=bearer(user_token)).status_code == 403


# ---------- the primitive ----------

def test_delete_prefix_handles_none_one_and_many(s3_bucket):
    assert storage.delete_prefix("results/nothing-here/") == (0, 0)

    _put("results/one/a.txt", b"abc")
    assert storage.delete_prefix("results/one/") == (1, 3)

    for i in range(5):
        _put(f"results/many/f{i}.txt", b"xy")
    n, freed = storage.delete_prefix("results/many/")
    assert (n, freed) == (5, 10)
    assert not storage.object_exists("results/many/f0.txt")


def test_delete_prefix_refuses_to_empty_the_bucket(s3_bucket):
    _put("results/keep/a.txt")
    for bad in ("", "/", "*"):
        with pytest.raises(ValueError, match="whole bucket"):
            storage.delete_prefix(bad)
    assert storage.object_exists("results/keep/a.txt")
