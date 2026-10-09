"""Pembatasan akses server-side untuk laporan nilai persediaan (P0 Reporting Foundation).

`/api/reports/valuation-summary` & `/api/reports/valuation-ledger` (doc_procurement.py) sebelumnya hanya memeriksa izin
`view_purchase_price` + isolasi tenant -> pengguna berizin harga dapat melihat nilai SELURUH gudang/divisi tenant.
Layer ini mengganti kedua route dengan versi ber-scope, BENTUK RESPON TETAP SAMA (kompatibel):
  - gudang dibatasi rule cakupan existing Master Barang/Inventory (`stock_summary.allowed/assigned_warehouses/wh_in_scope`):
    divisi pengguna + penugasan gudang (bila ada); pengguna global tidak dibatasi;
  - `warehouse_id` di luar cakupan -> 403 (bukan daftar kosong diam-diam);
  - tanpa batas 5000 baris (tidak ada pemotongan diam-diam);
  - filter tanggal valuation-ledger memakai TANGGAL EFEKTIF WIB (tanggal transaksi `txn_at`, fallback waktu posting `at`)
    = semantik cut-off `stock_summary.value_as_of_fn`. Urutan baris tetap urutan posting (`at`) seperti sebelumnya.
Read-only: tidak mengubah engine/formula MWA, valuation ledger, maupun transaksi.
"""
from fastapi import Depends, HTTPException

import stock_summary as SS
from reporting.scope import local_day

LEDGER_FIELDS = ("doc_type", "doc_no", "at", "qty_in", "qty_out", "unit_cost", "value_in", "value_out", "qty_before",
                 "value_before", "avg_before", "qty_after", "value_after", "avg_after", "valuation_method",
                 "valuation_estimated")


def effective_day(row) -> str:
    """Tanggal efektif bisnis (WIB) entri ledger: tanggal transaksi, fallback waktu posting."""
    return local_day(row.get("txn_at") or row.get("at"))


async def scoped_warehouses(server, user, warehouse_id=None):
    """(daftar id gudang dalam cakupan, peta id->gudang). `warehouse_id` di luar cakupan -> 403."""
    alw, assigned = SS.allowed(server, user), SS.assigned_warehouses(server, user)
    whs = await server.db.warehouses.find({}, {"_id": 0, "id": 1, "name": 1, "code": 1, "division_id": 1}).to_list(None)
    wmap = {w["id"]: w for w in whs if w.get("id")}
    ids = [w["id"] for w in wmap.values() if SS.wh_in_scope(w, alw, assigned)]
    if warehouse_id:
        if warehouse_id not in ids:
            raise HTTPException(403, "Gudang ini berada di luar cakupan Anda.")
        ids = [warehouse_id]
    return ids, wmap


def _require_value(server, user):
    server.require(user, "view")
    if not server.has_perm(user, "view_purchase_price"):
        raise HTTPException(403, "Tidak memiliki akses nilai persediaan")


async def _items(server, ids):
    if not ids:
        return {}
    rows = await server.db.items.find({"id": {"$in": sorted(ids)}}, {"_id": 0, "id": 1, "name": 1, "code": 1,
                                                                       "base_uom_id": 1}).to_list(None)
    return {r["id"]: r for r in rows}


async def valuation_summary_rows(server, user, item_id=None, warehouse_id=None):
    _require_value(server, user)
    wh_ids, wmap = await scoped_warehouses(server, user, warehouse_id)
    if not wh_ids:
        return []
    q = {"warehouse_id": {"$in": wh_ids}}
    if item_id:
        q["item_id"] = item_id
    pools = await server.db.item_warehouse.find(q, {"_id": 0}).to_list(None)
    pools = [r for r in pools if not (float(r.get("current_stock") or 0) == 0 and float(r.get("total_value") or 0) == 0)]
    im = await _items(server, {r.get("item_id") for r in pools if r.get("item_id")})
    out = []
    for r in pools:
        it = im.get(r.get("item_id"), {})
        out.append({"item_id": r.get("item_id"), "item_name": it.get("name"), "item_code": it.get("code"),
                    "warehouse_id": r.get("warehouse_id"), "warehouse_name": wmap.get(r.get("warehouse_id"), {}).get("name"),
                    "qty_on_hand": float(r.get("current_stock") or 0), "base_uom": it.get("base_uom_id"),
                    "avg_cost": float(r.get("avg_cost") or 0), "inventory_value": float(r.get("total_value") or 0)})
    out.sort(key=lambda x: (x["item_name"] or "", x["warehouse_name"] or ""))
    return out


async def valuation_ledger_rows(server, user, item_id=None, warehouse_id=None, doc_type=None, date_from=None, date_to=None):
    _require_value(server, user)
    wh_ids, wmap = await scoped_warehouses(server, user, warehouse_id)
    if not wh_ids:
        return []
    q = {"warehouse_id": {"$in": wh_ids}}
    if item_id:
        q["item_id"] = item_id
    if doc_type:
        q["doc_type"] = doc_type
    rows = await server.db.valuation_ledger.find(q, {"_id": 0}).sort("at", 1).to_list(None)
    sel = []
    for r in rows:
        d = effective_day(r)
        if (date_from and d < date_from) or (date_to and d > date_to):
            continue
        sel.append(r)
    im = await _items(server, {r.get("item_id") for r in sel if r.get("item_id")})
    return [{**{k: r.get(k) for k in LEDGER_FIELDS}, "txn_date": effective_day(r),
             "item_name": im.get(r.get("item_id"), {}).get("name"),
             "warehouse_name": wmap.get(r.get("warehouse_id"), {}).get("name")} for r in sel]


def install(server):
    app = server.app

    def drop(path):
        for r in [r for r in app.router.routes if getattr(r, "path", None) == path and "GET" in (getattr(r, "methods", None) or set())]:
            app.router.routes.remove(r)

    drop("/api/reports/valuation-summary")
    drop("/api/reports/valuation-ledger")

    async def valuation_summary(item_id: str = None, warehouse_id: str = None, user=Depends(server.current_user)):
        out = await valuation_summary_rows(server, user, item_id, warehouse_id)
        return {"method": "moving_weighted_average", "rows": out,
                "total_value": round(sum(x["inventory_value"] for x in out), 4)}

    async def valuation_ledger(item_id: str = None, warehouse_id: str = None, doc_type: str = None,
                               date_from: str = None, date_to: str = None, user=Depends(server.current_user)):
        return {"rows": await valuation_ledger_rows(server, user, item_id, warehouse_id, doc_type, date_from, date_to)}

    app.add_api_route("/api/reports/valuation-summary", valuation_summary, methods=["GET"], tags=["reports-scope"])
    app.add_api_route("/api/reports/valuation-ledger", valuation_ledger, methods=["GET"], tags=["reports-scope"])
