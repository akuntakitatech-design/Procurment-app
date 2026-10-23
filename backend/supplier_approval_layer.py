"""Approval Supplier — supplier baru wajib disetujui atasan sebelum dipakai di PO.

Status disimpan pada dokumen supplier (`approval_status`): `pending` | `approved` | `rejected`.
- Supplier lama tanpa field ini dianggap `approved` (backward compatible).
- Supplier `pending`/`rejected` tidak muncul di lookup (form PO, dsb) dan ditolak di API PO,
  sehingga aturan tetap berlaku walau request dibuat langsung ke API.
- Approval dilakukan di menu Approval (tab Supplier) dan mendukung approval massal.

Tidak mengubah engine approval dokumen (approval_tasks) yang sudah ada; ini alur ringan khusus master supplier.
"""
from fastapi import Depends, HTTPException

APPROVED = "approved"
PENDING = "pending"
REJECTED = "rejected"
STATUSES = (PENDING, APPROVED, REJECTED)


def _status(supplier) -> str:
    value = (supplier or {}).get("approval_status")
    return value if value in STATUSES else APPROVED


def _find_route(app, path, method):
    for route in app.router.routes:
        if getattr(route, "path", None) != path:
            continue
        if method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def install(server):
    app = server.app

    def _db():
        # Diambil saat request: tenant_isolation_layer memasang proxy tenant ke server.db setelah layer ini.
        return server.db

    async def _supplier(supplier_id):
        if not supplier_id:
            return None
        return await _db().suppliers.find_one({"id": supplier_id}, {"_id": 0})

    async def ensure_approved(supplier_id):
        """Guard dipakai sebelum PO dibuat/diubah (juga mencegah bypass lewat API langsung)."""
        supplier = await _supplier(supplier_id)
        if not supplier:
            return
        if _status(supplier) != APPROVED:
            label = "menunggu approval" if _status(supplier) == PENDING else "ditolak"
            raise HTTPException(
                400,
                f"Supplier {supplier.get('name')} masih {label}. Supplier baru harus disetujui atasan "
                f"di menu Approval → Supplier sebelum dipakai di PO.",
            )

    # ---------------------------------------------------------------- routes
    create_po_route = _find_route(app, "/api/po", "POST")
    if create_po_route:
        original_create_po = create_po_route.endpoint

        async def create_po_guarded(body: dict, user=Depends(server.current_user)):
            await ensure_approved((body or {}).get("supplier_id"))
            return await original_create_po(body=body, user=user)

        idx = app.router.routes.index(create_po_route)
        app.router.routes.remove(create_po_route)
        app.add_api_route("/api/po", create_po_guarded, methods=["POST"], tags=["supplier-approval"])
        app.router.routes.insert(idx, app.router.routes.pop())

    edit_route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if edit_route:
        original_edit = edit_route.endpoint

        async def edit_guarded(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module == "po":
                await ensure_approved((body or {}).get("supplier_id"))
            return await original_edit(module=module, did=did, body=body, user=user)

        idx = app.router.routes.index(edit_route)
        app.router.routes.remove(edit_route)
        app.add_api_route("/api/transactions/{module}/{did}", edit_guarded, methods=["PUT"], tags=["supplier-approval"])
        app.router.routes.insert(idx, app.router.routes.pop())

    master_create = _find_route(app, "/api/master/{name}", "POST")
    if master_create:
        original_master_create = master_create.endpoint

        async def master_create_guarded(name: str, body: dict, user=Depends(server.current_user)):
            result = await original_master_create(name=name, body=body, user=user)
            if name != "suppliers" or not isinstance(result, dict) or not result.get("id"):
                return result
            patch = {
                "approval_status": PENDING,
                "approval_requested_by": user.get("email"),
                "approval_requested_by_name": user.get("name") or user.get("email"),
                "approval_requested_at": server.now_iso(),
                "approval_acted_by": None,
                "approval_acted_by_name": None,
                "approval_acted_at": None,
                "approval_note": None,
            }
            await _db().suppliers.update_one({"id": result["id"]}, {"$set": patch})
            result.update(patch)
            await server.notify(
                "Supplier baru menunggu approval",
                f"{result.get('name')} diajukan oleh {patch['approval_requested_by']}",
                "approval",
            )
            return result

        idx = app.router.routes.index(master_create)
        app.router.routes.remove(master_create)
        app.add_api_route("/api/master/{name}", master_create_guarded, methods=["POST"], tags=["supplier-approval"])
        app.router.routes.insert(idx, app.router.routes.pop())

    # ------------------------------------------------------------- endpoints
    @app.get("/api/supplier-approvals", tags=["supplier-approval"])
    async def list_supplier_approvals(status: str = "pending", q: str = None, user=Depends(server.current_user)):
        server.require(user, "view")
        rows = await _db().suppliers.find({}, {"_id": 0}).sort("created_at", -1).to_list(20000)
        counts = {PENDING: 0, APPROVED: 0, REJECTED: 0}
        for row in rows:
            counts[_status(row)] += 1
        wanted = status if status in STATUSES else None
        out = [r for r in rows if wanted is None or _status(r) == wanted]
        if q:
            needle = q.strip().lower()
            out = [r for r in out
                   if needle in str(r.get("code") or "").lower() or needle in str(r.get("name") or "").lower()]
        fields = ("id", "code", "name", "legal_name", "city", "phone", "email", "supplier_category_id",
                  "approval_status", "approval_requested_by", "approval_requested_by_name", "approval_requested_at",
                  "approval_acted_by", "approval_acted_by_name", "approval_acted_at", "approval_note",
                  "is_active", "created_at")
        items = []
        for row in out:
            item = {k: row.get(k) for k in fields}
            item["approval_status"] = _status(row)
            items.append(item)
        return {"items": items, "counts": counts}

    async def _act(ids, user, new_status, note):
        ids = [x for x in (ids or []) if x]
        if not ids:
            raise HTTPException(400, "Pilih minimal satu supplier")
        rows = await _db().suppliers.find({"id": {"$in": ids}}, {"_id": 0}).to_list(5000)
        if not rows:
            raise HTTPException(404, "Supplier tidak ditemukan")
        now = server.now_iso()
        done = []
        for row in rows:
            if _status(row) != PENDING:
                continue  # sudah diproses / bukan kandidat: lewati (idempoten)
            await _db().suppliers.update_one({"id": row["id"]}, {"$set": {
                "approval_status": new_status,
                "approval_acted_by": user.get("email"),
                "approval_acted_by_name": user.get("name") or user.get("email"),
                "approval_acted_at": now,
                "approval_note": note,
            }})
            await server.audit(user, "approve" if new_status == APPROVED else "reject",
                               "suppliers", row["id"], row.get("code"), reason=note)
            done.append(row.get("code") or row.get("name"))
        if not done:
            raise HTTPException(409, "Tidak ada supplier berstatus menunggu approval pada pilihan ini")
        action_label = "disetujui" if new_status == APPROVED else "ditolak"
        preview = ", ".join([x for x in done[:5]]) + ("…" if len(done) > 5 else "")
        await server.notify(f"{len(done)} supplier {action_label}", preview, "approval")
        return {"ok": True, "updated": len(done), "status": new_status, "codes": done}

    @app.post("/api/supplier-approvals/approve", tags=["supplier-approval"])
    async def approve_suppliers(body: dict = None, user=Depends(server.current_user)):
        server.require(user, "approve")
        body = body or {}
        return await _act(body.get("ids") or [], user, APPROVED, body.get("note"))

    @app.post("/api/supplier-approvals/reject", tags=["supplier-approval"])
    async def reject_suppliers(body: dict = None, user=Depends(server.current_user)):
        server.require(user, "approve")
        body = body or {}
        note = str(body.get("reason") or "").strip()
        if not note:
            raise HTTPException(400, "Alasan penolakan wajib diisi")
        return await _act(body.get("ids") or [], user, REJECTED, note)