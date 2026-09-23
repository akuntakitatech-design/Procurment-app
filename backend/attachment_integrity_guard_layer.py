"""Integrity guard for transaction attachments.

Ensures uploaded files belong to a real transaction in the active tenant, enforces
reasonable business-document file types and upload size, and prevents orphan files.
"""
import os
from pathlib import Path

from fastapi import File, Form, HTTPException, Request, UploadFile

import storage as S


ENTITY_COLLECTIONS = {
    "mro": "mro",
    "ro": "ro",
    "po": "po",
    "do": "do",
    "mi": "mi",
    "transfer": "transfers",
    "loan": "loans",
    "loan_return": "loan_returns",
    "adjustment": "adjustments",
    "opname": "opname",
}

ALLOWED_EXTENSIONS = {
    "pdf", "jpg", "jpeg", "png", "webp",
    "xls", "xlsx", "doc", "docx", "csv", "txt",
}


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _max_upload_bytes():
    try:
        mb = float(os.environ.get("MAX_UPLOAD_MB", "15") or 15)
    except (TypeError, ValueError):
        mb = 15
    mb = max(1, min(100, mb))
    return int(mb * 1024 * 1024), mb


async def _validate_file(file: UploadFile):
    filename = Path(str(file.filename or "")).name
    if not filename or len(filename) > 255:
        raise HTTPException(400, "Nama file lampiran tidak valid")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Jenis file lampiran tidak didukung")

    expected = S.MIME_TYPES.get(ext)
    ctype = str(file.content_type or "").lower().split(";", 1)[0].strip()
    # Some browsers use generic binary MIME for office documents; accept it when extension is safe.
    if ctype not in ("", "application/octet-stream") and expected and ctype != expected:
        # jpg/jpeg intentionally share image/jpeg in S.MIME_TYPES.
        raise HTTPException(400, "Tipe file tidak sesuai dengan ekstensi lampiran")

    max_bytes, max_mb = _max_upload_bytes()
    data = await file.read(max_bytes + 1)
    await file.seek(0)
    if not data:
        raise HTTPException(400, "File lampiran kosong")
    if len(data) > max_bytes:
        raise HTTPException(400, f"Ukuran lampiran maksimal {max_mb:g} MB")


def install(server):
    app = server.app
    route = _find_route(app, "/api/attachments", "POST")
    if not route:
        return
    original = route.endpoint
    app.router.routes.remove(route)

    async def guarded_upload(
        request: Request,
        file: UploadFile = File(...),
        entity: str = Form(...),
        entity_id: str = Form(...),
        category: str = Form("Lainnya"),
        note: str = Form(""),
    ):
        user = await server.current_user(request)
        server.require(user, "upload_attachment")

        entity = str(entity or "").strip().lower()
        entity_id = str(entity_id or "").strip()
        collection = ENTITY_COLLECTIONS.get(entity)
        if not collection:
            raise HTTPException(400, "Jenis transaksi lampiran tidak dikenal")
        if not entity_id:
            raise HTTPException(400, "ID transaksi lampiran wajib diisi")
        if not await getattr(server.db, collection).find_one({"id": entity_id}, {"_id": 0, "id": 1}):
            raise HTTPException(404, "Transaksi tujuan lampiran tidak ditemukan")

        if len(str(category or "")) > 100:
            raise HTTPException(400, "Kategori lampiran terlalu panjang")
        if len(str(note or "")) > 1000:
            raise HTTPException(400, "Catatan lampiran terlalu panjang")
        await _validate_file(file)
        return await original(request, file, entity, entity_id, category, note)

    app.add_api_route("/api/attachments", guarded_upload, methods=["POST"], tags=["attachments"])
