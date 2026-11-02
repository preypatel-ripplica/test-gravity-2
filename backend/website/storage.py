"""Cloudflare R2 helpers for website media uploads (CMS_NEW parity)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def _clean_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        return "upload"
    return "".join(
        char if char.isalnum() or char in {".", "-", "_"} else "-" for char in name
    )


def r2_is_configured() -> bool:
    return all(
        [
            os.getenv("STORAGE_PROVIDER") == "r2",
            os.getenv("R2_BUCKET_NAME"),
            os.getenv("R2_ENDPOINT"),
            os.getenv("R2_ACCESS_KEY_ID"),
            os.getenv("R2_SECRET_ACCESS_KEY"),
        ]
    )


def get_r2_bucket_name() -> str:
    bucket_name = (os.getenv("R2_BUCKET_NAME") or "").strip()
    if not bucket_name:
        raise ValueError("R2_BUCKET_NAME is not configured")
    return bucket_name


def get_r2_client():
    if not r2_is_configured():
        raise ValueError("R2 storage is not configured")

    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def build_r2_object_key(project_id: str, filename: str) -> str:
    safe_name = _clean_filename(filename)
    return f"media/{project_id}/{uuid4().hex}-{safe_name}"


def build_r2_public_url(object_key: str) -> str:
    public_base_url = (os.getenv("R2_PUBLIC_BASE_URL") or "").rstrip("/")
    if public_base_url:
        return f"{public_base_url}/{object_key}"

    endpoint = (os.getenv("R2_ENDPOINT") or "").rstrip("/")
    bucket_name = get_r2_bucket_name()
    return f"{endpoint}/{bucket_name}/{object_key}"


def generate_r2_upload_url(object_key: str, content_type: str, expires_in: int = 3600) -> str:
    client = get_r2_client()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": get_r2_bucket_name(),
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def put_r2_object(object_key: str, content: bytes, content_type: str) -> None:
    client = get_r2_client()
    client.put_object(
        Bucket=get_r2_bucket_name(),
        Key=object_key,
        Body=content,
        ContentType=content_type or "application/octet-stream",
    )
