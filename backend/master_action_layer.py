"""Master Data standard actions: stronger delete protection, bulk delete preflight,
safe DELETE for SPK / Kontrak Harga Vendor / Stok Min-Max. Reuses master_delete_guard_layer."""
from fastapi import Depends, HTTPException

import master_delete_guard_layer as G

LABELS = {**G.MASTER_LABELS, "spk": "SPK", "vendor_contracts": "Kontrak Harga Vendor", "item_warehouse": "Stok Min/Max"}
EPS = 1e-9


def _find_route(app, path, method):
    for r in list(app.router.routes):
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set()):
            return r
    return None


async def _exists(db, coll, query):
    return await getattr(db, coll).find_one(query, {"_id": 0}) is not None


async def _extra_reason(server, name, rid, doc):
    db = server.db
    if name == "items":
        if await db.item_warehouse.find_one({"item_id": rid, "$or": [{"current_stock": {"$gt": EPS}}, {"current_stock": {"$lt": -EPS}}, {"total_value": {"$gt": EPS}}, {"total_value": {"$lt": -EPS}}]}, {"_id": 0}):
            return "masih memiliki saldo stok / nilai persediaan"
        if await _exists(db, "valuation_ledger", {"item_id": rid}):
            return "sudah memiliki riwayat valuasi persediaan"
        if await _exists(db, "vendor_contract_items", {"item_id": rid}):
            return "sudah digunakan pada Kontrak Harga Vendor"
    if name == "warehouses":
        if await db.item_warehouse.find_one({"warehouse_id": rid, "$or": [{"current_stock": {"$gt": EPS}}, {"current_stock": {"$lt": -EPS}}, {"total_value": {"$gt": EPS}}, {"total_value": {"$lt": -EPS}}]}, {"_id": 0}):
            return "masih memiliki saldo stok"
        if await _exists(db, "valuation_ledger", {"warehouse_id": rid}):
            return "sudah memiliki riwayat valuasi persediaan"
    if name == "suppliers":
        if await _exists(db, "vendor_contracts", {"supplier_id": rid}):
            return "sudah digunakan pada Kontrak Harga Vendor"
    if name == "uoms" and await _exists(db, "vendor_contract_items", {"uom_id": rid}):
        return "sudah digunakan pada Kontrak Harga Vendor"
    if name == "projects":
        if await _exists(db, "spk", {"project_id": rid}):
            return "sudah digunakan pada SPK"
        if await _exists(db, "units", {"project_id": rid}):
            return "masih terhubung dengan Unit / Aset"
    if name == "divisions":
        for coll, label in (("projects", "Proyek"), ("spk", "SPK")):
            if await _exists(db, coll, {"division_id": rid}):
                return f"masih digunakan oleh {label}"
    if name == "contacts":
        for coll in ("projects", "warehouses", "spk"):
            if await _exists(db, coll, {"pic_id": rid}):
                return "masih menjadi PIC pada data lain"
    if name == "item_categories":
        n = await db.items.count_documents({"category_id": rid})
        if n:
            return f"masih digunakan oleh {n} barang"
    if name == "supplier_categories":
        n = await db.suppliers.count_documents({"supplier_category_id": rid})
        if n:
            return f"masih digunakan oleh {n} supplier"
    if name == "spk":
        if await _exists(db, "procurement_item_spk_allocations", {"spk_id": rid}):
            return "sudah digunakan pada alokasi SPK transaksi (MRO/RO/PO/DO/MI)"
        for coll, label in (("spk_addendums", "addendum"), ("spk_budget_allocations", "alokasi budget"), ("spk_documents", "dokumen")):
            if await _exists(db, coll, {"spk_id": rid}):
                return f"sudah memiliki {label}"
        num = doc.get("spk_number")
        for coll in ("mro", "ro", "po", "do", "mi"):
            if num and await _exists(db, coll, {"spk": num}):
                return f"sudah direferensikan oleh transaksi {coll.upper()}"
    if name == "vendor_contracts":
        num = doc.get("contract_number")
        if num and await _exists(db, "po_lines", {"contract_number_snapshot": num}):
            return "sudah digunakan sebagai harga pada PO"
        if await _exists(db, "vendor_contract_price_history", {"contract_id": rid}):
            return "sudah memiliki riwayat perubahan harga"
        if await _exists(db, "vendor_contract_documents", {"contract_id": rid}):
            return "masih memiliki dokumen terlampir"
    return None


def _iw_key(rid):
    item_id, _, warehouse_id = str(rid or "").partition("|")
    return {"item_id": item_id, "warehouse_id": warehouse_id}


async def _iw_reason(server, rid):
    row = await server.db.item_warehouse.find_one(_iw_key(rid), {"_id": 0})
    if not row:
        return None, "Data tidak ditemukan"
    item = await server.db.items.find_one({"id": row["item_id"]}, {"_id": 0, "code": 1, "name": 1}) or {}
    wh = await server.db.warehouses.find_one({"id": row["warehouse_id"]}, {"_id": 0, "name": 1}) or {}
    row = {**row, "code": item.get("code"), "name": f"{item.get('name') or '-'} @ {wh.get('name') or '-'}"}
    if not float(row.get("min_stock") or 0) and not float(row.get("max_stock") or 0):
        return row, "belum memiliki konfigurasi Stok Min/Max"
    return row, None


def _coll(server, name):
    if name in ("spk", "vendor_contracts"):
        return getattr(server.db, name)
    if name not in server.MASTER_COLLECTIONS:
        raise HTTPException(404, "Master tidak ditemukan")
    return server._mc(name)


async def delete_reason(server, name, rid):
    if name == "item_warehouse":
        return await _iw_reason(server, rid)
    doc = await _coll(server, name).find_one({"id": rid}, {"_id": 0})
    if not doc:
        return None, "Data tidak ditemukan"
    r = await _extra_reason(server, name, rid, doc)
    if not r and name not in ("spk", "vendor_contracts"):
        hit = await G._dependency(server, name, rid)
        if hit:
            r = f"sudah digunakan pada transaksi / data terkait ({hit})"
    return doc, r


def _label_of(doc):
    code = doc.get("code") or doc.get("spk_number") or doc.get("contract_number") or ""
    name = doc.get("name") or doc.get("project_name") or doc.get("title") or ""
    return " — ".join(x for x in (str(code), str(name)) if x) or "-"


def install(server):
    app = server.app

    async def _delete(name, rid, user):
        server.require(user, "delete")
        doc, reason = await delete_reason(server, name, rid)
        if doc is None:
            raise HTTPException(404, "Data tidak ditemukan")
        if reason:
            raise HTTPException(409, f"{LABELS.get(name, 'Data')} tidak dapat dihapus karena {reason}. Silakan nonaktifkan data apabila sudah tidak digunakan.")

    old = _find_route(app, "/api/master/{name}/{rid}", "DELETE")
    if old:
        orig = old.endpoint
        app.router.routes.remove(old)

        async def delete_master(name: str, rid: str, user=Depends(server.current_user)):
            await _delete(name, rid, user)
            return await orig(name=name, rid=rid, user=user)

        app.add_api_route("/api/master/{name}/{rid}", delete_master, methods=["DELETE"], tags=["master"])

    async def _hard_delete(name, rid, user, children=()):
        await _delete(name, rid, user)
        doc = await getattr(server.db, name).find_one({"id": rid}, {"_id": 0})
        for coll, fk in children:
            await getattr(server.db, coll).delete_many({fk: rid})
        await getattr(server.db, name).delete_one({"id": rid})
        await server.audit(user, "delete", name, rid, _label_of(doc), before=doc, reason=f"{LABELS[name]} dihapus karena belum pernah digunakan")
        return {"ok": True, "deleted": True}

    @app.delete("/api/spk/{spk_id}", tags=["spk"])
    async def delete_spk(spk_id: str, user=Depends(server.current_user)):
        return await _hard_delete("spk", spk_id, user)

    @app.delete("/api/vendor-contracts/{cid}", tags=["vendor_contract"])
    async def delete_vendor_contract(cid: str, user=Depends(server.current_user)):
        return await _hard_delete("vendor_contracts", cid, user, children=(("vendor_contract_items", "contract_id"),))

    @app.post("/api/master-delete-check/{name}", tags=["master"])
    async def delete_check(name: str, body: dict, user=Depends(server.current_user)):
        server.require(user, "delete")
        out = []
        for rid in (body or {}).get("ids") or []:
            doc, reason = await delete_reason(server, name, rid)
            out.append({"id": rid, "label": _label_of(doc or {}), "ok": doc is not None and not reason,
                        "reason": reason if doc is not None else "Data tidak ditemukan"})
        return out

    async def _clear_minmax(rid, user):
        server.require(user, "delete")
        row, reason = await _iw_reason(server, rid)
        if row is None:
            raise HTTPException(404, "Konfigurasi Stok Min/Max tidak ditemukan")
        if reason:
            raise HTTPException(409, f"Stok Min/Max tidak dapat dihapus karena {reason}.")
        # Removes only the Min/Max configuration — never the stock pool, quantity or valuation.
        await server.db.item_warehouse.update_one(_iw_key(rid), {"$set": {"min_stock": 0, "max_stock": 0}})
        await server.audit(user, "delete", "stok_min_max", rid, _label_of(row),
                           before={"min_stock": row.get("min_stock"), "max_stock": row.get("max_stock")},
                           after={"min_stock": 0, "max_stock": 0}, reason="Konfigurasi Stok Min/Max dihapus")
        return {"ok": True}

    @app.post("/api/item-warehouse/clear-minmax", tags=["master"])
    async def clear_minmax(body: dict, user=Depends(server.current_user)):
        b = body or {}
        return await _clear_minmax(f"{b.get('item_id')}|{b.get('warehouse_id')}", user)

    iw_set = _find_route(app, "/api/item-warehouse", "POST")
    if iw_set:
        orig_set = iw_set.endpoint
        app.router.routes.remove(iw_set)

        async def item_warehouse_set(body: dict, user=Depends(server.current_user)):
            server.require(user, "edit")
            b = body or {}
            item = await server.db.items.find_one({"id": b.get("item_id")}, {"_id": 0, "code": 1, "name": 1})
            wh = await server.db.warehouses.find_one({"id": b.get("warehouse_id")}, {"_id": 0, "name": 1})
            if not item or not wh:
                raise HTTPException(404, "Barang atau Gudang tidak ditemukan")
            before = await server.db.item_warehouse.find_one({"item_id": b["item_id"], "warehouse_id": b["warehouse_id"]}, {"_id": 0}) or {}
            res = await orig_set(body=b, user=user)
            await server.audit(user, "edit", "stok_min_max", f"{b['item_id']}|{b['warehouse_id']}",
                               f"{item.get('code')} — {item.get('name')} @ {wh.get('name')}",
                               before={"min_stock": before.get("min_stock"), "max_stock": before.get("max_stock")},
                               after={"min_stock": b.get("min_stock", 0), "max_stock": b.get("max_stock", 0)})
            return res

        app.add_api_route("/api/item-warehouse", item_warehouse_set, methods=["POST"], tags=["stock-safety"])

    async def _delete_one(name, rid, user):
        if name == "item_warehouse":
            return await _clear_minmax(rid, user)
        if name == "spk":
            return await _hard_delete("spk", rid, user)
        if name == "vendor_contracts":
            return await _hard_delete("vendor_contracts", rid, user, children=(("vendor_contract_items", "contract_id"),))
        return await delete_master(name=name, rid=rid, user=user)

    @app.post("/api/master-bulk-delete/{name}", tags=["master"])
    async def bulk_delete(name: str, body: dict, user=Depends(server.current_user)):
        # All-or-nothing: every selected record is checked first; any blocked record cancels the whole batch.
        server.require(user, "delete")
        ids = list(dict.fromkeys((body or {}).get("ids") or []))
        if not ids:
            raise HTTPException(400, "Pilih minimal satu data untuk dihapus")
        blocked = []
        for rid in ids:
            doc, reason = await delete_reason(server, name, rid)
            if doc is None or reason:
                blocked.append(f"{_label_of(doc or {})} ({reason or 'Data tidak ditemukan'})")
        if blocked:
            raise HTTPException(409, f"Hapus dibatalkan — {len(blocked)} data tidak dapat dihapus: {'; '.join(blocked)}. Tidak ada data yang dihapus. Batalkan pilihan data yang diblok terlebih dahulu.")
        for rid in ids:
            await _delete_one(name, rid, user)
        return {"ok": True, "deleted": len(ids)}
