"""Integrity guard for transaction attachments.

Ensures uploaded files belong to a real transaction in the active tenant, enforces
reasonable business-document file types and upload size, and prevents orphan files.
"""
import os
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile

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
    "po_approval2_batch": "po_approval2_batches",  # bukti persetujuan Pengajuan Approval 2 PO
    "supplier": "suppliers",  # Dokumen Supplier (Master Supplier)
    "transfer_draft": "attachment_drafts",  # lampiran Transfer sebelum posting (milik user, di-bind saat posting)
}
DRAFT_ENTITIES = {"transfer_draft": "transfer"}


async def _assert_draft_owner(server, entity, entity_id, user, for_upload=False):
    """Draft lampiran hanya boleh diakses pemiliknya (tenant sudah diisolasi otomatis oleh tenant layer)."""
    d = await server.db.attachment_drafts.find_one({"id": entity_id, "module": DRAFT_ENTITIES[entity]}, {"_id": 0})
    if not d or d.get("owner_id") != user.get("id") or d.get("deleted"):
        raise HTTPException(404, "Transaksi tujuan lampiran tidak ditemukan")
    if for_upload:
        if d.get("bound_to"):
            raise HTTPException(409, "Draft lampiran sudah terikat ke transaksi")
        if not server.has_perm(user, f"{DRAFT_ENTITIES[entity]}.create"):
            raise HTTPException(403, "Anda tidak memiliki izin untuk menambah data")
    return d

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
        if entity in DRAFT_ENTITIES:
            await _assert_draft_owner(server, entity, entity_id, user, for_upload=True)
        elif not await getattr(server.db, collection).find_one({"id": entity_id}, {"_id": 0, "id": 1}):
            raise HTTPException(404, "Transaksi tujuan lampiran tidak ditemukan")

        if len(str(category or "")) > 100:
            raise HTTPException(400, "Kategori lampiran terlalu panjang")
        if len(str(note or "")) > 1000:
            raise HTTPException(400, "Catatan lampiran terlalu panjang")
        await _validate_file(file)
        return await original(request, file, entity, entity_id, category, note)

    app.add_api_route("/api/attachments", guarded_upload, methods=["POST"], tags=["attachments"])

    # Draft: list hanya untuk pemilik; pemilik boleh menghapus lampiran draft-nya sendiri sebelum posting.
    r_list = _find_route(app, "/api/attachments", "GET")
    if r_list:
        orig_list = r_list.endpoint
        app.router.routes.remove(r_list)

        async def guarded_list(entity: str, entity_id: str, user=Depends(server.current_user)):
            if str(entity or "").strip().lower() in DRAFT_ENTITIES:
                await _assert_draft_owner(server, str(entity).strip().lower(), entity_id, user)
            return await orig_list(entity=entity, entity_id=entity_id, user=user)
        app.add_api_route("/api/attachments", guarded_list, methods=["GET"], tags=["attachments"])

    r_del = _find_route(app, "/api/attachments/{aid}", "DELETE")
    if r_del:
        orig_del = r_del.endpoint
        app.router.routes.remove(r_del)

        async def guarded_delete(aid: str, user=Depends(server.current_user)):
            rec = await server.db.attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0})
            if rec and rec.get("entity") in DRAFT_ENTITIES:
                # Hanya pemilik draft (tenant sama) & berizin membuat Transfer; file draft dihapus fisik.
                await _assert_draft_owner(server, rec["entity"], rec.get("entity_id"), user, for_upload=True)
                try:
                    S.delete_object(rec.get("storage_path") or "")
                except Exception:  # noqa: BLE001 - object hilang tidak menggagalkan hapus
                    pass
                await server.db.attachments.delete_one({"id": aid, "entity": rec["entity"]})
                return {"ok": True}
            return await orig_del(aid=aid, user=user)
        app.add_api_route("/api/attachments/{aid}", guarded_delete, methods=["DELETE"], tags=["attachments"])

    # Download lampiran DRAFT: hanya pemilik draft. Lampiran entity lain tetap memakai alur existing apa adanya.
    r_dl = _find_route(app, "/api/attachments/{aid}/download", "GET")
    if r_dl:
        orig_dl = r_dl.endpoint
        app.router.routes.remove(r_dl)

        async def guarded_download(aid: str, request: Request, auth: str = Query(None)):
            rec = await server.db.attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0, "entity": 1, "entity_id": 1})
            if rec and rec.get("entity") in DRAFT_ENTITIES:
                user = None
                try:
                    user = await server.current_user(request)
                except HTTPException:
                    if auth:
                        import tenant_security_hardening_layer as TSH
                        user = await TSH._user_from_query_token(server, auth)
                if not user:
                    raise HTTPException(401, "Not authenticated")
                await _assert_draft_owner(server, rec["entity"], rec.get("entity_id"), user)
            return await orig_dl(aid=aid, request=request, auth=auth)
        app.add_api_route("/api/attachments/{aid}/download", guarded_download, methods=["GET"], tags=["attachments"])

    # Cleanup draft lampiran Transfer orphan (> 24 jam, belum ter-bind) saat startup; juga dipanggil endpoint draft.
    @app.on_event("startup")
    async def _transfer_draft_cleanup_startup():
        try:
            import transfer_lines as TL
            await TL.cleanup_expired_drafts(server, all_tenants=True)
        except Exception:  # noqa: BLE001 - cleanup tidak boleh menggagalkan startup
            pass
