"""Master Barang — daftar barang + posisi stok per gudang (server-side pagination).

Endpoint baru (read-only, tidak mengubah endpoint lama):
    GET /api/master-items/stock-list
        ?page=1&page_size=25|50|100&q=&category_id=&warehouse_id=&division_id=
        &active=Aktif|Nonaktif&stock_status=Normal|Low Stock|Out of Stock|Overstock|No Stock
        &sort=code|name|category_label|unit_label|division_label|total_stock|stock_status|created_at&dir=asc|desc

Urutan penegakan: tenant (sesi + proxy isolasi) -> izin modul `items.view` -> cakupan divisi barang
-> cakupan gudang (divisi gudang + penugasan gudang) -> business rule status stok existing.

Sumber kebenaran stok = koleksi `item_warehouse` (current_stock, min_stock, max_stock) yang hanya
digerakkan oleh ledger transaksi. Tidak ada perhitungan stok baru, tidak ada nilai HPP/rata-rata.

Pola query per request (tanpa N+1):
    1. lookup ringan paralel: warehouses, divisions, item_categories, uoms (4 query, tabel kecil)
    2. 1 query daftar barang (filter kategori/divisi di-pushdown ke SQL)
    3. 1 query agregat stok per barang (GROUP BY item_id di MariaDB) -> ringkasan, filter & sort status
    4. 1 query batch stok per sel (item_id IN <barang di halaman aktif> AND warehouse_id IN <gudang scope>)
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request

SIZES = (25, 50, 100)
STATUSES = ("Normal", "Low Stock", "Out of Stock", "Overstock", "No Stock")
SORTS = {"code", "name", "category_label", "unit_label", "division_label", "total_stock", "stock_status", "created_at"}
STATUS_RANK = {"Out of Stock": 0, "Low Stock": 1, "Normal": 2, "Overstock": 3}
ITEM_PROJECTION = {"_id": 0}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def cell_status(cur, mn, mx) -> str:
    """Rule existing per barang-gudang (server.item_warehouse_list / doc_reports.stock_position)."""
    cur, mn, mx = _f(cur), _f(mn), _f(mx)
    if cur <= 0:
        return "Out of Stock"
    if cur <= mn:
        return "Low Stock"
    if mx and cur > mx:
        return "Overstock"
    return "Normal"


def item_status(total, min_total, max_total, records) -> str:
    """Rule level barang (Inventory / Posisi Stok): total vs jumlah min/max seluruh gudang.
    Total stok 0 = Stok Habis, termasuk barang yang belum punya catatan stok di gudang mana pun
    (sel gudangnya tetap tampil "Belum ada stok"; penanda `stock_records` = 0)."""
    total, min_total, max_total = _f(total), _f(min_total), _f(max_total)
    if total <= 0:
        return "Out of Stock"
    if min_total > 0 and total <= min_total:
        return "Low Stock"
    if max_total > 0 and total > max_total:
        return "Overstock"
    return "Normal"


def _size(v) -> int:
    try:
        v = int(v or 25)
    except (TypeError, ValueError):
        return 25
    return v if v in SIZES else 25


def _page(v) -> int:
    try:
        return max(1, int(v or 1))
    except (TypeError, ValueError):
        return 1


def _skey(v):
    if v is None or v == "":
        return (2, 0.0, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (0, float(v), "")
    return (1, 0.0, str(v).lower())


def _item_divisions(it) -> list:
    ids = [it["division_id"]] if it.get("division_id") else []
    for d in it.get("division_ids") or []:
        if d and d not in ids:
            ids.append(d)
    return ids


def install(server):
    app = server.app
    import tenant_foundation_layer as TF
    import tenant_isolation_layer as TI

    def allowed(user) -> Optional[set]:
        return None if server.is_global(user) else {str(x) for x in (user.get("divisions") or []) if x}

    def assigned_warehouses(user) -> set:
        if server.is_global(user) or "view_all_warehouse" in (user.get("permissions") or []):
            return set()
        return {str(x) for x in (user.get("warehouses") or []) if x}

    def can_view_items(user) -> bool:
        return user.get("role") == "admin" or "items.view" in set(user.get("effective_permissions") or [])

    def item_in_scope(it, alw) -> bool:
        if alw is None:
            return True
        divs = _item_divisions(it)
        return not divs or all(d in alw for d in divs)

    def wh_in_scope(w, alw, wh_ids) -> bool:
        if alw is not None and w.get("division_id") and w["division_id"] not in alw:
            return False
        return not wh_ids or w["id"] in wh_ids

    async def stock_aggregate(wh_ids: list, user) -> dict:
        """{item_id: (total, min_total, max_total, records)} untuk gudang scope; dihitung di database."""
        if not wh_ids:
            return {}
        if server.DB_BACKEND == "mariadb":
            raw = server.client[os.environ.get("DB_NAME", "default")]
            await raw._ensure_table("item_warehouse")
            tenant = TI.current_tenant_id() or TF.tenant_id_of(user)
            marks = ", ".join(["%s"] * len(wh_ids))
            sql = ("SELECT item_id, SUM(COALESCE(CAST(current_stock AS DOUBLE), 0)), "
                   "SUM(COALESCE(CAST(min_stock AS DOUBLE), 0)), SUM(COALESCE(CAST(max_stock AS DOUBLE), 0)), COUNT(*) "
                   f"FROM `item_warehouse` WHERE tenant_id = %s AND warehouse_id IN ({marks}) GROUP BY item_id")
            rows = await raw._fetchall(sql, [tenant, *wh_ids])
            return {r[0]: (float(r[1] or 0), float(r[2] or 0), float(r[3] or 0), int(r[4] or 0)) for r in rows if r[0]}
        pipeline = [{"$match": {"warehouse_id": {"$in": wh_ids}}},
                    {"$group": {"_id": "$item_id", "total": {"$sum": "$current_stock"}, "mn": {"$sum": "$min_stock"},
                                "mx": {"$sum": "$max_stock"}, "n": {"$sum": 1}}}]
        rows = await server.db.item_warehouse.aggregate(pipeline).to_list(None)
        return {r["_id"]: (_f(r.get("total")), _f(r.get("mn")), _f(r.get("mx")), int(r.get("n") or 0)) for r in rows if r.get("_id")}

    @app.get("/api/master-items/stock-list", tags=["master-item-stock"])
    async def master_item_stock_list(request: Request, user=Depends(server.current_user)):
        if not can_view_items(user):
            raise HTTPException(403, "Anda tidak memiliki izin untuk melihat data Barang.")
        qp = dict(request.query_params)
        size, page = _size(qp.get("page_size")), _page(qp.get("page"))
        alw, wh_assigned = allowed(user), assigned_warehouses(user)
        db = server.db

        whs, divs, cats, uoms = await asyncio.gather(
            db.warehouses.find({}, {"_id": 0, "id": 1, "code": 1, "name": 1, "division_id": 1, "is_active": 1}).to_list(5000),
            db.divisions.find({}, {"_id": 0, "id": 1, "code": 1, "name": 1, "is_active": 1}).to_list(5000),
            db.item_categories.find({}, {"_id": 0, "id": 1, "name": 1, "is_active": 1}).to_list(5000),
            db.uoms.find({}, {"_id": 0, "id": 1, "name": 1, "symbol": 1, "code": 1}).to_list(5000),
        )
        scoped_whs = [w for w in whs if w.get("id") and w.get("is_active") is not False and wh_in_scope(w, alw, wh_assigned)]
        scoped_whs.sort(key=lambda w: (str(w.get("name") or "").lower(), str(w.get("code") or "")))
        div_name = {d["id"]: d.get("name") for d in divs if d.get("id")}
        cat_name = {c["id"]: c.get("name") for c in cats if c.get("id")}
        uom_label = {u["id"]: (u.get("symbol") or u.get("code") or u.get("name")) for u in uoms if u.get("id")}

        warehouse_id = (qp.get("warehouse_id") or "").strip()
        division_id = (qp.get("division_id") or "").strip()
        category_id = (qp.get("category_id") or "").strip()
        if warehouse_id:
            col_whs = [w for w in scoped_whs if w["id"] == warehouse_id]
            if not col_whs:
                raise HTTPException(403, "Gudang ini berada di luar cakupan Anda atau tidak aktif.")
        else:
            col_whs = scoped_whs
        if division_id and alw is not None and division_id not in alw:
            raise HTTPException(403, "Divisi ini berada di luar cakupan divisi Anda.")

        flt: dict = {}
        if category_id:
            flt["category_id"] = category_id
        if division_id:
            flt["division_id"] = division_id
        elif alw is not None:
            flt["division_id"] = {"$in": sorted(alw) + [None, ""]}  # barang tanpa divisi tetap terlihat (rule in_scope existing)
        col_ids = [w["id"] for w in col_whs]
        items_raw, agg = await asyncio.gather(db.items.find(flt, ITEM_PROJECTION).to_list(100000), stock_aggregate(col_ids, user))

        active = qp.get("active") or ""
        terms = (qp.get("q") or "").strip().lower().split()
        rows = []
        for it in items_raw:
            if not it.get("id") or not item_in_scope(it, alw):
                continue
            if active == "Aktif" and not it.get("is_active"):
                continue
            if active == "Nonaktif" and it.get("is_active"):
                continue
            a = agg.get(it["id"])
            if warehouse_id and not a:
                continue  # filter gudang = barang yang memiliki catatan stok di gudang tsb
            if terms:
                hay = " ".join(str(it.get(k) or "") for k in ("code", "name", "alias", "part_number", "brand")).lower()
                if not all(t in hay for t in terms):
                    continue
            total, mn, mx, n = a or (0.0, 0.0, 0.0, 0)
            names = [div_name.get(d) or "-" for d in _item_divisions(it) if alw is None or d in alw]
            rows.append({**it,
                         "category_label": cat_name.get(it.get("category_id")) or it.get("category") or None,
                         "division_label": ", ".join(names) if names else None,
                         "unit_label": uom_label.get(it.get("base_uom_id")) or it.get("unit") or None,
                         "status_label": "Aktif" if it.get("is_active") else "Nonaktif",
                         "total_stock": round(total, 6), "stock_records": n,
                         "stock_status": item_status(total, mn, mx, n)})

        # out_of_stock mencakup barang tanpa catatan stok; no_stock = bagian dari out_of_stock (informasi).
        summary = {"total": len(rows), "out_of_stock": 0, "low_stock": 0, "overstock": 0, "normal": 0, "no_stock": 0}
        key = {"Out of Stock": "out_of_stock", "Low Stock": "low_stock", "Overstock": "overstock", "Normal": "normal"}
        for r in rows:
            summary[key[r["stock_status"]]] += 1
            if not r["stock_records"]:
                summary["no_stock"] += 1

        st = qp.get("stock_status") or ""
        if st == "No Stock":
            rows = [r for r in rows if not r["stock_records"]]
        elif st in STATUSES:
            rows = [r for r in rows if r["stock_status"] == st]

        sort = qp.get("sort") if qp.get("sort") in SORTS else None
        desc = qp.get("dir") == "desc"
        if sort:
            getv = (lambda r: STATUS_RANK[r["stock_status"]]) if sort == "stock_status" else (lambda r: r.get(sort))
            filled = [r for r in rows if getv(r) not in (None, "")]
            empty = [r for r in rows if getv(r) in (None, "")]
            filled.sort(key=lambda r: (_skey(getv(r)), str(r.get("code") or "")), reverse=desc)
            rows = filled + empty
        else:  # default sama dengan Master Data: terbaru dahulu
            rows.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("code") or "")), reverse=True)

        total = len(rows)
        page = min(page, max(1, -(-total // size)))
        page_rows = rows[(page - 1) * size: page * size]

        # Batch stok per sel hanya untuk barang di halaman aktif (1 query, IN item_id x IN warehouse_id).
        cells = {}
        if page_rows and col_ids:
            iws = await db.item_warehouse.find(
                {"item_id": {"$in": [r["id"] for r in page_rows]}, "warehouse_id": {"$in": col_ids}},
                {"_id": 0, "item_id": 1, "warehouse_id": 1, "current_stock": 1, "min_stock": 1, "max_stock": 1}).to_list(None)
            for iw in iws:
                cur = _f(iw.get("current_stock"))
                cells.setdefault(iw["item_id"], {})[iw["warehouse_id"]] = {
                    "qty": cur, "min": _f(iw.get("min_stock")), "max": _f(iw.get("max_stock")),
                    "status": cell_status(cur, iw.get("min_stock"), iw.get("max_stock"))}
        for r in page_rows:
            r["stock"] = cells.get(r["id"], {})

        div_opts = [{"id": d["id"], "name": d.get("name")} for d in divs
                    if d.get("id") and d.get("is_active") is not False and (alw is None or d["id"] in alw)]
        div_opts.sort(key=lambda d: str(d.get("name") or "").lower())
        cat_opts = sorted([{"id": c["id"], "name": c.get("name")} for c in cats if c.get("id") and c.get("is_active") is not False],
                          key=lambda c: str(c.get("name") or "").lower())
        return {"items": page_rows, "total": total, "page": page, "page_size": size, "summary": summary,
                "warehouses": [{"id": w["id"], "code": w.get("code"), "name": w.get("name")} for w in col_whs],
                "filters": {"warehouses": [{"id": w["id"], "code": w.get("code"), "name": w.get("name")} for w in scoped_whs],
                            "divisions": div_opts, "categories": cat_opts}}
