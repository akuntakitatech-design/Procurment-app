#!/usr/bin/env python3
"""
Migrasi lampiran lokal ProcureFlow -> Cloudflare R2 (S3-compatible).

Sumber: folder hasil ekstrak `local-attachments.tar.gz` (atau file tar.gz langsung).
Key objek di R2 = path relatif yang sama (mis. `procureflow/uploads/po/<uuid>.pdf`,
`procureflow/branding/company-logo.jpg`, `settings/po-signature.jpg`) sehingga nilai
`storage_path` / `logo_path` di database tetap valid tanpa perubahan.

Env yang dibaca (sama dengan backend/storage.py): R2_ENDPOINT|S3_ENDPOINT, R2_ACCESS_KEY_ID|S3_ACCESS_KEY,
R2_SECRET_ACCESS_KEY|S3_SECRET_KEY, R2_BUCKET|S3_BUCKET.

Contoh:
  python scripts/migrate_attachments_to_r2.py --source /path/local-attachments.tar.gz
  python scripts/migrate_attachments_to_r2.py --source /app/data/uploads
"""
import argparse
import mimetypes
import os
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402


def env(*names, default=""):
    for n in names:
        v = os.environ.get(n, "").strip()
        if v: return v
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="folder uploads atau file .tar.gz")
    ap.add_argument("--prefix", default="", help="prefix tambahan di bucket (opsional)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    endpoint = env("R2_ENDPOINT", "S3_ENDPOINT") or (f"https://{env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com" if env("R2_ACCOUNT_ID") else "")
    bucket = env("R2_BUCKET", "S3_BUCKET")
    key_id = env("R2_ACCESS_KEY_ID", "S3_ACCESS_KEY")
    secret = env("R2_SECRET_ACCESS_KEY", "S3_SECRET_KEY")
    if not (endpoint and bucket and key_id and secret):
        print("Env R2/S3 belum lengkap (endpoint, bucket, access key, secret)."); sys.exit(2)

    s3 = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key_id, aws_secret_access_key=secret,
                      region_name=env("S3_REGION", default="auto"), config=Config(signature_version="s3v4"))

    src = Path(args.source)
    tmp = None
    if src.is_file() and src.suffixes[-2:] in ([".tar", ".gz"],) or str(src).endswith(".tgz"):
        tmp = tempfile.mkdtemp(prefix="attach-")
        with tarfile.open(src) as tar:
            tar.extractall(tmp)
        root = Path(tmp)
    else:
        root = src

    files = [p for p in root.rglob("*") if p.is_file()]
    print(f"[upload] {len(files)} file dari {root} -> {endpoint}/{bucket}")
    ok = 0
    for p in sorted(files):
        rel = p.relative_to(root).as_posix()
        key = f"{args.prefix.strip('/')}/{rel}" if args.prefix else rel
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        print(f"  {key}  ({p.stat().st_size} B, {ctype})")
        if not args.dry_run:
            s3.put_object(Bucket=bucket, Key=key, Body=p.read_bytes(), ContentType=ctype)
            head = s3.head_object(Bucket=bucket, Key=key)
            assert head["ContentLength"] == p.stat().st_size, f"ukuran tidak cocok: {key}"
        ok += 1
    print(f"Selesai: {ok}/{len(files)} file{' (dry-run)' if args.dry_run else ''}.")


if __name__ == "__main__":
    main()
