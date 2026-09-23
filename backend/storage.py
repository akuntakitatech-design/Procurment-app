"""Self-hosted attachment storage.

Supported drivers:
- local: stores files under STORAGE_LOCAL_PATH
- minio/s3: stores files in an S3-compatible bucket (MinIO recommended)
"""
import logging
import mimetypes
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

APP_NAME = "procureflow"


def _env(*names, default=""):
    """Ambil env pertama yang terisi. Mendukung alias R2_* (Cloudflare R2) dan S3_* (MinIO/S3)."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


_R2_ACCOUNT_ID = _env("R2_ACCOUNT_ID")
STORAGE_DRIVER = _env("STORAGE_DRIVER", default="local").lower()
if STORAGE_DRIVER == "r2":
    STORAGE_DRIVER = "s3"
LOCAL_PATH = Path(_env("STORAGE_LOCAL_PATH", default="/app/data/uploads"))
S3_ENDPOINT = _env("R2_ENDPOINT", "S3_ENDPOINT",
                   default=(f"https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if _R2_ACCOUNT_ID else "http://minio:9000"))
S3_ACCESS_KEY = _env("R2_ACCESS_KEY_ID", "S3_ACCESS_KEY")
S3_SECRET_KEY = _env("R2_SECRET_ACCESS_KEY", "S3_SECRET_KEY")
S3_BUCKET = _env("R2_BUCKET", "S3_BUCKET", default="procureflow").lower()
S3_REGION = _env("S3_REGION", default=("auto" if "r2.cloudflarestorage.com" in S3_ENDPOINT else "us-east-1"))
IS_R2 = "r2.cloudflarestorage.com" in S3_ENDPOINT

MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "json": "application/json",
    "csv": "text/csv", "txt": "text/plain",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_s3 = None


def _safe_local_path(object_path: str) -> Path:
    clean = object_path.replace("\\", "/").lstrip("/")
    if ".." in clean.split("/"):
        raise ValueError("Invalid storage path")
    target = (LOCAL_PATH / clean).resolve()
    root = LOCAL_PATH.resolve()
    if root != target and root not in target.parents:
        raise ValueError("Invalid storage path")
    return target


def _s3_client():
    global _s3
    if _s3 is None:
        if not S3_ACCESS_KEY or not S3_SECRET_KEY:
            raise RuntimeError("S3_ACCESS_KEY dan S3_SECRET_KEY wajib untuk STORAGE_DRIVER=minio/s3")
        _s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(signature_version="s3v4"),
        )
    return _s3


def init_storage(force: bool = False):
    if STORAGE_DRIVER == "local":
        LOCAL_PATH.mkdir(parents=True, exist_ok=True)
        logger.info("Attachment storage: local (%s)", LOCAL_PATH)
        return str(LOCAL_PATH)

    if STORAGE_DRIVER in ("minio", "s3"):
        client = _s3_client()
        try:
            client.head_bucket(Bucket=S3_BUCKET)
        except ClientError as exc:
            if IS_R2:
                # Token R2 umumnya tidak berhak membuat bucket; bucket harus sudah ada.
                raise RuntimeError(f"Bucket R2 '{S3_BUCKET}' tidak dapat diakses: {exc}") from exc
            client.create_bucket(Bucket=S3_BUCKET)
        logger.info("Attachment storage: %s (%s/%s)", "r2" if IS_R2 else STORAGE_DRIVER, S3_ENDPOINT, S3_BUCKET)
        return S3_BUCKET

    raise RuntimeError(f"Unsupported STORAGE_DRIVER: {STORAGE_DRIVER}")


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if STORAGE_DRIVER == "local":
        target = _safe_local_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": path, "size": len(data)}

    if STORAGE_DRIVER in ("minio", "s3"):
        client = _s3_client()
        client.put_object(
            Bucket=S3_BUCKET,
            Key=path,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        return {"path": path, "size": len(data)}

    raise RuntimeError(f"Unsupported STORAGE_DRIVER: {STORAGE_DRIVER}")


def get_object(path: str):
    if STORAGE_DRIVER == "local":
        target = _safe_local_path(path)
        if not target.exists():
            raise FileNotFoundError(path)
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return target.read_bytes(), content_type

    if STORAGE_DRIVER in ("minio", "s3"):
        client = _s3_client()
        response = client.get_object(Bucket=S3_BUCKET, Key=path)
        return response["Body"].read(), response.get("ContentType", "application/octet-stream")

    raise RuntimeError(f"Unsupported STORAGE_DRIVER: {STORAGE_DRIVER}")
