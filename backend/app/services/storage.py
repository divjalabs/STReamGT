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

# 16 MiB minimum part: small enough that a stalled part is cheap to retry. For very large
# files the part size scales up (see choose_part_size) so the count stays bounded.
DEFAULT_PART_SIZE = 16 * 1024 * 1024
_MIB = 1024 * 1024


def choose_part_size(size: int, target_parts: int = 500) -> int:
    """Pick a part size: at least 16 MiB, but grow it for huge files so we stay ~<=500 parts
    (S3 hard-caps at 10k). e.g. 2 GB -> 16 MiB (128 parts); 50 GB -> ~100 MiB (500 parts)."""
    want = max(DEFAULT_PART_SIZE, -(-size // target_parts))  # ceil(size/target)
    return -(-want // _MIB) * _MIB  # round up to a whole MiB


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
    """Single-shot presigned PUT for small files (e.g. a sample .xlsx).

    Content-Type is intentionally NOT signed: the browser sets its own Content-Type from the
    file (e.g. application/gzip), and signing a fixed one here would cause a signature mismatch.
    """
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.presign_expire_seconds,
    )


def presign_get(key: str, filename: str | None = None, inline: bool = False,
                content_type: str | None = None) -> str:
    """Presigned GET. By default sets an attachment disposition (download); when inline=True it
    serves inline (e.g. so an HTML report renders in a browser tab) with the given content_type."""
    params = {"Bucket": settings.s3_bucket, "Key": key}
    if inline:
        if content_type:
            params["ResponseContentType"] = content_type
    elif filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return _client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=settings.presign_expire_seconds
    )


def start_multipart(key: str, size: int, part_size: int | None = None) -> MultipartUpload:
    """Initiate a multipart upload and presign one PUT URL per part."""
    if part_size is None:
        part_size = choose_part_size(size)
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


def put_bytes(key: str, body: bytes, content_type: str = "text/csv") -> None:
    """Store in-memory bytes (e.g. an uploaded panel CSV) directly to S3."""
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=body, ContentType=content_type)


def object_exists(key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError:
        return False
