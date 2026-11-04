"""Google Cloud Storage for WhatsApp media.

Media the customer sends (and media the bot sends from our own store) lives in a
PRIVATE GCS bucket. Objects are never public: the inbox reads them through the
backend proxy (GET /media/{message_id}) and Meta fetches them via a short-lived
signed URL minted at send time.

Credentials come from env as a service-account JSON string (GCP_SA_KEY_JSON) so
the same config works locally and on Vercel; the bucket name is GCS_BUCKET. The
client + bucket are built lazily and cached so import never touches the network.
"""

from __future__ import annotations


import datetime
import json
import os
import uuid
from typing import Optional

from google.cloud import storage
from google.oauth2 import service_account

_client: Optional[storage.Client] = None
_bucket_name: Optional[str] = None


def _load_client_and_bucket() -> tuple[storage.Client, str]:
    """Build (once) a storage.Client from GCP_SA_KEY_JSON and the GCS_BUCKET
    name. Raises a clear RuntimeError if either env var is missing/invalid so
    callers can log it and keep the webhook alive."""
    global _client, _bucket_name

    if _client is not None and _bucket_name is not None:
        return _client, _bucket_name

    raw_key = os.getenv("GCP_SA_KEY_JSON")
    bucket_name = os.getenv("GCS_BUCKET")

    if not raw_key:
        raise RuntimeError("GCP_SA_KEY_JSON is not configured.")
    if not bucket_name:
        raise RuntimeError("GCS_BUCKET is not configured.")

    try:
        info = json.loads(raw_key)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"GCP_SA_KEY_JSON is not valid JSON: {error}") from error

    credentials = service_account.Credentials.from_service_account_info(info)
    _client = storage.Client(project=info.get("project_id"), credentials=credentials)
    _bucket_name = bucket_name
    return _client, _bucket_name


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    """gs://bucket/key -> (bucket, key)."""
    if not gcs_uri.startswith("gs://"):
        raise RuntimeError(f"Not a gs:// URI: {gcs_uri}")
    without_scheme = gcs_uri[len("gs://"):]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise RuntimeError(f"Malformed gs:// URI: {gcs_uri}")
    return bucket, key


_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "audio/mpeg": ".mp3",   # transcoded audio we store (both directions)
    "audio/ogg": ".ogg",    # inbound voice note if the MP3 transcode fails and we store the original
}


def extension_for_mime(mime_type: Optional[str], fallback: str = "") -> str:
    """Pick a file extension from a mime type (best-effort)."""
    if not mime_type:
        return fallback
    return _EXT_BY_MIME.get(mime_type.split(";")[0].strip(), fallback)


def upload_bytes(data: bytes, content_type: str, ext: str = "", prefix: str = "whatsapp-media") -> str:
    """Store bytes under a random key and return the gs:// URI. Object is
    private (bucket uses uniform access; we never make it public)."""
    client, bucket_name = _load_client_and_bucket()
    key = f"{prefix.strip('/')}/{uuid.uuid4().hex}{ext or extension_for_mime(content_type)}"
    blob = client.bucket(bucket_name).blob(key)
    blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
    return f"gs://{bucket_name}/{key}"


def download_bytes(gcs_uri: str) -> tuple[bytes, str]:
    """Fetch an object's bytes + content type (for the inbox proxy stream)."""
    client, _ = _load_client_and_bucket()
    bucket, key = _parse_gcs_uri(gcs_uri)
    blob = client.bucket(bucket).blob(key)
    blob.reload()  # populate content_type
    data = blob.download_as_bytes()
    return data, (blob.content_type or "application/octet-stream")


def generate_signed_url(gcs_uri: str, minutes: int = 15) -> str:
    """Mint a short-lived V4 signed HTTPS URL so Meta can fetch a private
    object on outbound send. Signing is offline via the SA private key."""
    client, _ = _load_client_and_bucket()
    bucket, key = _parse_gcs_uri(gcs_uri)
    blob = client.bucket(bucket).blob(key)
    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=minutes),
        method="GET",
    )
