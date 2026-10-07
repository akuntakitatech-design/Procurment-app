"""Dokumen Supplier — memakai attachment engine existing (/api/attachments + storage existing).

entity = "supplier", entity_id = supplier.id. Binary tidak disimpan di database (hanya metadata attachment).
Keamanan: tenant isolation (proxy tenant pada koleksi suppliers/attachments) -> hak akses Master Supplier:
  - lihat/daftar/unduh  : suppliers.view
  - unggah              : upload_attachment + suppliers.edit
  - hapus (soft delete) : upload_attachment + suppliers.edit
Kategori dibatasi pada daftar resmi Dokumen Supplier.
"""
from __future__ import annotations

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile

ENTITY = "supplier"
CATEGORIES = ["NPWP", "KTP", "NIB", "SIUP", "Akta Perusahaan", "Rekening Bank", "Surat Penawaran", "Kontrak",
              "Dokumen Pendukung", "Lainnya"]
MSG_NOT_FOUND = "Supplier tidak ditemukan"


def _find_route(app, path, method):
    return next((r for r in app.router.routes if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set())), None)


def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731
    cu = server.current_user

    def need(user, key, verb):
        if not server.has_perm(user, key):
            raise HTTPException(403, f"Anda tidak memiliki izin untuk {verb}")

    async def load_supplier(sid):
        sup = await db().suppliers.find_one({"id": str(sid or "").strip()}, {"_id": 0, "id": 1, "name": 1, "code": 1})
        if not sup:
            raise HTTPException(404, MSG_NOT_FOUND)
        return sup

    @app.get("/api/supplier-documents/categories", tags=["supplier-documents"])
    async def categories(user=Depends(cu)):
        need(user, "suppliers.view", "melihat dokumen supplier")
        return CATEGORIES

    r_up = _find_route(app, "/api/attachments", "POST")
    if r_up:
        orig_up = r_up.endpoint
        app.router.routes.remove(r_up)

        async def upload(request: Request, file: UploadFile = File(...), entity: str = Form(...), entity_id: str = Form(...),
                         category: str = Form("Lainnya"), note: str = Form("")):
            if str(entity or "").strip().lower() != ENTITY:
                return await orig_up(request, file, entity, entity_id, category, note)
            user = await cu(request)
            server.require(user, "upload_attachment")
            need(user, "suppliers.edit", "mengunggah dokumen supplier")
            sup = await load_supplier(entity_id)
            cat = str(category or "").strip()
            if cat not in CATEGORIES:
                raise HTTPException(400, "Kategori dokumen supplier tidak valid")
            res = await orig_up(request, file, ENTITY, sup["id"], cat, str(note or "").strip())
            if isinstance(res, dict) and res.get("id"):
                await db().attachments.update_one({"id": res["id"]}, {"$set": {"uploaded_by_email": user.get("email")}})
            await server.audit(user, "upload_supplier_document", ENTITY, sup["id"], sup.get("name"),
                               after={"file": (res or {}).get("original_filename"), "category": cat})
            return {k: v for k, v in res.items() if k != "storage_path"} if isinstance(res, dict) else res
        app.add_api_route("/api/attachments", upload, methods=["POST"], tags=["supplier-documents"])

    r_list = _find_route(app, "/api/attachments", "GET")
    if r_list:
        orig_list = r_list.endpoint
        app.router.routes.remove(r_list)

        async def list_att(entity: str, entity_id: str, user=Depends(cu)):
            if str(entity or "").strip().lower() == ENTITY:
                need(user, "suppliers.view", "melihat dokumen supplier")
                sup = await load_supplier(entity_id)
                rows = await db().attachments.find({"entity": ENTITY, "entity_id": sup["id"], "is_deleted": False},
                                                   {"_id": 0, "storage_path": 0}).sort("created_at", -1).to_list(500)
                return rows
            return await orig_list(entity=entity, entity_id=entity_id, user=user)
        app.add_api_route("/api/attachments", list_att, methods=["GET"], tags=["supplier-documents"])

    r_dl = _find_route(app, "/api/attachments/{aid}/download", "GET")
    if r_dl:
        orig_dl = r_dl.endpoint
        app.router.routes.remove(r_dl)

        async def download(aid: str, request: Request, auth: str = Query(None)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0, "entity": 1, "entity_id": 1})
            if rec and rec.get("entity") == ENTITY:
                user = await cu(request)
                need(user, "suppliers.view", "melihat dokumen supplier")
                await load_supplier(rec.get("entity_id"))
            return await orig_dl(aid=aid, request=request, auth=auth)
        app.add_api_route("/api/attachments/{aid}/download", download, methods=["GET"], tags=["supplier-documents"])

    r_del = _find_route(app, "/api/attachments/{aid}", "DELETE")
    if r_del:
        orig_del = r_del.endpoint
        app.router.routes.remove(r_del)

        async def delete_att(aid: str, user=Depends(cu)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0})
            if not rec or rec.get("entity") != ENTITY:
                return await orig_del(aid=aid, user=user)
            server.require(user, "upload_attachment")
            need(user, "suppliers.edit", "menghapus dokumen supplier")
            sup = await load_supplier(rec.get("entity_id"))
            # Soft delete metadata satu attachment saja (mekanisme existing); file lain tidak tersentuh.
            await db().attachments.update_one({"id": aid}, {"$set": {"is_deleted": True, "deleted_by": user.get("email"),
                                                                   "deleted_at": server.now_iso()}})
            await server.audit(user, "delete_supplier_document", ENTITY, sup["id"], sup.get("name"),
                               before={"file": rec.get("original_filename"), "category": rec.get("category")})
            return {"ok": True}
        app.add_api_route("/api/attachments/{aid}", delete_att, methods=["DELETE"], tags=["supplier-documents"])
