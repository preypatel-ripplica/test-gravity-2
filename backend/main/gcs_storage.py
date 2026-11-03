import json
from pathlib import Path
from google.cloud import storage
from google.oauth2 import service_account

from app.config import settings

def _get_gcs_client() -> storage.Client:
    """Initialize GCS client using either JSON string from env var or the local credentials file."""
    if settings.GCS_KEY_JSON:
        # Render/production: use the inline JSON string
        credentials_dict = json.loads(settings.GCS_KEY_JSON)
        credentials = service_account.Credentials.from_service_account_info(credentials_dict)
        return storage.Client(credentials=credentials, project=credentials.project_id)
    
    # Local: relies on GOOGLE_APPLICATION_CREDENTIALS env var
    return storage.Client()


def upload_bytes(folder: str, filename: str, data: bytes, content_type: str = "image/png") -> str:
    """Upload raw bytes to GCS and return the public URL."""
    if not settings.GCS_BUCKET_NAME:
        raise ValueError("GCS_BUCKET_NAME is not set in config.")
        
    client = _get_gcs_client()
    bucket = client.bucket(settings.GCS_BUCKET_NAME)
    
    # Ensure folder name ends with a slash if provided
    prefix = f"{folder.strip('/')}/" if folder else ""
    blob_path = f"{prefix}{filename}"
    
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    
    return f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/{blob_path}"


def _is_upload_timeout(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in text or "timed out" in text


class _ProgressReader:
    """Count bytes the storage client actually reads, then report a real percent."""

    def __init__(self, raw, total: int, on_progress):
        self._raw = raw
        self._total = total
        self._on_progress = on_progress
        self._read = 0
        self._last = -1

    def read(self, size=-1):
        data = self._raw.read(size)
        if data and self._total:
            self._read += len(data)
            percent = min(100, int(self._read * 100 / self._total))
            if percent != self._last:
                self._last = percent
                self._on_progress(percent)
        return data

    def seek(self, offset, whence=0):
        return self._raw.seek(offset, whence)

    def tell(self):
        return self._raw.tell()


def upload_file(folder: str, local_path: Path | str, content_type: str = "application/pdf", on_progress=None) -> str:
    """Upload a local file to GCS and return the public URL."""
    if not settings.GCS_BUCKET_NAME:
        raise ValueError("GCS_BUCKET_NAME is not set in config.")
        
    path = Path(local_path)
    client = _get_gcs_client()
    bucket = client.bucket(settings.GCS_BUCKET_NAME)
    
    prefix = f"{folder.strip('/')}/" if folder else ""
    blob_path = f"{prefix}{path.name}"
    
    blob = bucket.blob(blob_path)
    size = path.stat().st_size if path.exists() else 0
    # We set this 1 hour limit. The storage client itself stops at 2 minutes, which drops a large video.
    # If the copy does not finish in 1 hour, Instagram and Facebook are not posted.
    if content_type.startswith("video/") or size > 32 * 1024 * 1024:
        from google.api_core import retry as api_retry

        deadline = 3600.0
        blob.chunk_size = 8 * 1024 * 1024
        try:
            if on_progress and size:
                with path.open("rb") as raw:
                    blob.upload_from_file(
                        _ProgressReader(raw, size, on_progress),
                        size=size,
                        content_type=content_type,
                        timeout=deadline,
                        retry=api_retry.Retry(deadline=deadline),
                    )
            else:
                blob.upload_from_filename(
                    str(path),
                    content_type=content_type,
                    timeout=deadline,
                    retry=api_retry.Retry(deadline=deadline),
                )
        except Exception as exc:
            if _is_upload_timeout(exc):
                raise TimeoutError(
                    "Storage upload timed out after 1 hour. "
                    "The video was not copied for Instagram or Facebook."
                ) from exc
            raise
    else:
        if content_type == "application/pdf":
            blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_filename(str(path), content_type=content_type)
        if content_type == "application/pdf":
            try:
                blob.patch()
            except Exception as exc:  # noqa: BLE001
                print(f"[gcs] could not patch cache_control on {blob_path}: {exc}", flush=True)

    if content_type.startswith("video/"):
        try:
            blob.make_public()
            print(f"[gcs] public read enabled for {blob_path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "uniform bucket-level access" in text.lower():
                print(
                    f"[gcs] {blob_path} uses bucket-level access, so per-file public ACL is skipped.",
                    flush=True,
                )
            else:
                print(f"[gcs] could not set a public ACL on {blob_path}: {exc}", flush=True)

    try:
        blob.reload()
        generation = getattr(blob, "generation", None)
    except Exception:
        generation = None
    url = f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/{blob_path}"
    if generation:
        return f"{url}?generation={generation}"
    return url


def delete_file(blob_path: str) -> None:
    """Delete a file from GCS."""
    if not settings.GCS_BUCKET_NAME:
        return
        
    try:
        client = _get_gcs_client()
        bucket = client.bucket(settings.GCS_BUCKET_NAME)
        blob = bucket.blob(blob_path)
        blob.delete()
    except Exception as e:
        print(f"Failed to delete GCS file {blob_path}: {e}", flush=True)
