"""S3 object storage: presigned uploads/downloads and worker-side transfer helpers.

Large FASTQ (~2GB) uses multipart: the browser PUTs each part directly to S3 with a
presigned URL, so bytes never transit the API. Small files (sample sheets) use a single
presigned PUT. The worker uses download_file/upload_file to stage inputs and publish results.

Works against real AWS or a MinIO/localstack endpoint (settings.s3_endpoint_url).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.config import Config

from app.config import settings

# 100 MiB parts -> ~20 parts for a 2GB file, well under S3's 10k-part limit.
DEFAULT_PART_SIZE = 100 * 1024 * 1024


@lru_cache
def _client():
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        config=Config(signature_version="s3v4"),
    )


@dataclass
class MultipartUpload:
    key: str
    upload_id: str
    part_size: int
    part_urls: list[str]  # presigned URL per part, 1-indexed by position


def presign_put(key: str, content_type: str = "application/octet-stream") -> str:
    """Single-shot presigned PUT for small files (e.g. a sample .xlsx)."""
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.presign_expire_seconds,
    )


def presign_get(key: str, filename: str | None = None) -> str:
    """Presigned GET for downloads; optional filename sets a download disposition."""
    params = {"Bucket": settings.s3_bucket, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return _client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=settings.presign_expire_seconds
    )


def start_multipart(key: str, size: int, part_size: int = DEFAULT_PART_SIZE) -> MultipartUpload:
    """Initiate a multipart upload and presign one PUT URL per part."""
    c = _client()
    resp = c.create_multipart_upload(Bucket=settings.s3_bucket, Key=key)
    upload_id = resp["UploadId"]
    num_parts = max(1, -(-size // part_size))  # ceil division
    urls = [
        c.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": i,
            },
            ExpiresIn=settings.presign_expire_seconds,
        )
        for i in range(1, num_parts + 1)
    ]
    return MultipartUpload(key=key, upload_id=upload_id, part_size=part_size, part_urls=urls)


def complete_multipart(key: str, upload_id: str, parts: list[dict]) -> None:
    """Finalize a multipart upload. `parts` = [{"PartNumber": int, "ETag": str}, ...]."""
    ordered = sorted(parts, key=lambda p: p["PartNumber"])
    _client().complete_multipart_upload(
        Bucket=settings.s3_bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": ordered},
    )


def abort_multipart(key: str, upload_id: str) -> None:
    _client().abort_multipart_upload(Bucket=settings.s3_bucket, Key=key, UploadId=upload_id)


# --- worker-side helpers ---

def download_file(key: str, dest_path: str) -> None:
    _client().download_file(settings.s3_bucket, key, dest_path)


def upload_file(src_path: str, key: str) -> None:
    _client().upload_file(src_path, settings.s3_bucket, key)


def object_exists(key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError:
        return False
