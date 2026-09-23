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
STORAGE_DRIVER = os.environ.get("STORAGE_DRIVER", "local").strip().lower()
LOCAL_PATH = Path(os.environ.get("STORAGE_LOCAL_PATH", "/app/data/uploads"))
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://minio:9000").strip()
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "").strip()
S3_BUCKET = os.environ.get("S3_BUCKET", "procureflow").strip().lower()
S3_REGION = os.environ.get("S3_REGION", "us-east-1").strip()

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
        except ClientError:
            client.create_bucket(Bucket=S3_BUCKET)
        logger.info("Attachment storage: %s (%s/%s)", STORAGE_DRIVER, S3_ENDPOINT, S3_BUCKET)
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
