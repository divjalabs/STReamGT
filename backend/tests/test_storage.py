"""S3 storage helpers, exercised against moto's mock S3."""
import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.services import storage


@pytest.fixture()
def s3_bucket():
    with mock_aws():
        storage._client.cache_clear()  # rebuild client inside the mock
        boto3.client("s3", region_name=settings.s3_region).create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.s3_region},
        )
        yield
        storage._client.cache_clear()


def test_upload_download_exists_roundtrip(tmp_path, s3_bucket):
    src = tmp_path / "in.txt"
    src.write_text("hello genotypes")
    key = "results/DIVJA240/job1/genotypes.txt"

    assert storage.object_exists(key) is False
    storage.upload_file(str(src), key)
    assert storage.object_exists(key) is True

    dest = tmp_path / "out.txt"
    storage.download_file(key, str(dest))
    assert dest.read_text() == "hello genotypes"


def test_presign_urls_contain_key(s3_bucket):
    put = storage.presign_put("uploads/1/abc/x.xlsx")
    assert "uploads/1/abc/x.xlsx" in put and "Signature" in put
    get = storage.presign_get("results/k/j/genotypes.txt", filename="genotypes.txt")
    assert "genotypes.txt" in get


def test_multipart_presigns_one_url_per_part(s3_bucket):
    # 250 MiB with 100 MiB parts -> 3 parts
    mp = storage.start_multipart("uploads/1/big/reads.fastq.gz", size=250 * 1024 * 1024)
    assert mp.upload_id and len(mp.part_urls) == 3
    storage.abort_multipart(mp.key, mp.upload_id)
