"""Canonical stock summary per ITEM — satu sumber kebenaran untuk Master Barang, Inventory, dan Dashboard.

Logic diekstrak apa adanya dari `master_item_stock_layer` (tanpa formula baru):
    jumlah_item  = jumlah Master Item unik dalam scope/filter (BUKAN jumlah baris item_warehouse)
    total_stock  = SUM(current_stock) seluruh gudang dalam scope; tanpa item_warehouse -> 0, stock_records = 0
    Stok Habis   = total_stock <= 0 (termasuk barang yang belum pernah punya item_warehouse)
    Stok Menipis = total_stock > 0 AND min_total > 0 AND total_stock <= min_total
    Overstock    = max_total > 0 AND total_stock > max_total
    min_total / max_total = SUM(min_stock / max_stock) gudang dalam scope.

Scope (urutan): tenant (proxy isolasi + WHERE tenant_id) -> cakupan divisi barang -> cakupan gudang
(gudang aktif, divisi gudang, penugasan gudang) -> filter gudang / divisi / kategori / status aktif / q.

Nilai Persediaan (opsional, `with_value=True`) HANYA membaca hasil engine valuation/MWA existing — tidak menghitung
ulang avg_cost / HPP dan tidak menulis apa pun:
    - per hari ini (as_of kosong / >= hari ini): Σ item_warehouse.total_value (= Valuation Summary)
    - per tanggal lampau: Σ value_after entri valuation_ledger TERAKHIR per item×gudang dengan tanggal transaksi
      <= as_of (urut tanggal transaksi lalu urutan posting) — sama dengan saldo di laporan Valuation Ledger.
Nilai mencakup SELURUH barang dalam scope (termasuk nonaktif yang masih bersaldo); filter aktif hanya untuk KPI status.
`unvalued_items` = barang unik yang punya stok tetapi belum bernilai (rule diagnostik `missing_average` dari
valuation-reconcile: qty > 0 dan avg <= 0), dihitung pada tanggal yang SAMA dengan nilai (hari ini = state pool saat ini,
historis = posisi valuation ledger per tanggal).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import HTTPException

SIZES = (25, 50, 100)
STATUSES = ("Normal", "Low Stock", "Out of Stock", "Overstock", "No Stock")
SORTS = {"code", "name", "category_label", "unit_label", "division_label", "total_stock", "stock_status", "created_at"}
STATUS_RANK = {"Out of Stock": 0, "Low Stock": 1, "Normal": 2, "Overstock": 3}
SUMMARY_KEY = {"Out of Stock": "out_of_stock", "Low Stock": "low_stock", "Overstock": "overstock", "Normal": "normal"}
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
    """Rule level barang: total vs jumlah min/max seluruh gudang dalam scope.
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


def missing_average(qty, avg) -> bool:
    """Rule diagnostik valuation-reconcile: pool punya stok tetapi belum punya rata-rata biaya (belum bernilai)."""
    return _f(qty) > 1e-6 and _f(avg) <= 0


def today_iso() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()


def _txn_day(r) -> str:
    """Tanggal efektif bisnis WIB (txn_at, fallback at) — sama dengan valuation-ledger & Pusat Laporan (P0/P1).
    Tanggal murni 'YYYY-MM-DD' tetap apa adanya; timestamp UTC dikonversi ke tanggal Asia/Jakarta."""
    from reporting.scope import local_day
    return local_day(r.get("txn_at") or r.get("at"))


async def value_as_of_fn(server, item_ids: set, wh_ids: list, as_of: str) -> tuple:
    """Posisi valuation per item×gudang PADA/SEBELUM `as_of`, hanya dari bukti yang ada (urutan: opening valuation /
    valuation ledger). Return (nilai, barang belum bernilai, barang yang nilai historisnya belum dapat direkonstruksi).
      - ada entri <= as_of     -> value_after entri terakhir (urut tanggal transaksi lalu urutan posting);
                                  qty_after > 0 & avg_after <= 0 -> "belum bernilai" (rule missing_average reconcile)
      - entri pertama > as_of  -> qty_before entri pertama = 0: pool belum ada (nilai 0);
                                  qty_before > 0: stok lama tanpa riwayat sebelum entri itu -> TIDAK direkonstruksi
      - tanpa entri sama sekali -> stok saat ini > 0: stok lama tanpa riwayat -> TIDAK direkonstruksi
    Nilai pool saat ini (item_warehouse.total_value) TIDAK pernah dipakai sebagai nilai masa lalu.
    Return (nilai, n barang belum bernilai, n barang & n pool (item×gudang) yang belum dapat direkonstruksi)."""
    if not item_ids or not wh_ids:
        return 0.0, 0, 0, 0
    wh = list(wh_ids)
    rows, pools = await asyncio.gather(
        server.db.valuation_ledger.find({"warehouse_id": {"$in": wh}},
                                        {"_id": 0, "item_id": 1, "warehouse_id": 1, "txn_at": 1, "at": 1, "qty_before": 1,
                                         "qty_after": 1, "value_after": 1, "avg_after": 1}).to_list(None),
        server.db.item_warehouse.find({"warehouse_id": {"$in": wh}}, {"_id": 0, "item_id": 1, "warehouse_id": 1, "current_stock": 1}).to_list(None))
    last, first = {}, {}
    for r in rows:
        if r.get("item_id") not in item_ids:
            continue
        key, order = (r["item_id"], r.get("warehouse_id")), (_txn_day(r), str(r.get("at") or ""))
        if key not in first or order < first[key][0]:
            first[key] = (order, r)
        if order[0] <= as_of and (key not in last or order >= last[key][0]):
            last[key] = (order, r)
    value, unvalued, unknown = 0.0, set(), set()
    for key, (_, r) in last.items():
        value += _f(r.get("value_after"))
        if missing_average(r.get("qty_after"), r.get("avg_after")):
            unvalued.add(key[0])
    for key, (_, r) in first.items():
        if key not in last and _f(r.get("qty_before")) > 1e-6:
            unknown.add(key)
    for p in pools:
        key = (p.get("item_id"), p.get("warehouse_id"))
        if key[0] in item_ids and key not in first and _f(p.get("current_stock")) > 1e-6:
            unknown.add(key)
    return round(value, 4), len(unvalued), len({k[0] for k in unknown}), len(unknown)


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


def allowed(server, user) -> Optional[set]:
    return None if server.is_global(user) else {str(x) for x in (user.get("divisions") or []) if x}


def assigned_warehouses(server, user) -> set:
    if server.is_global(user) or "view_all_warehouse" in (user.get("permissions") or []):
        return set()
    return {str(x) for x in (user.get("warehouses") or []) if x}


def item_in_scope(it, alw) -> bool:
    if alw is None:
        return True
    divs = _item_divisions(it)
    return not divs or all(d in alw for d in divs)


def wh_in_scope(w, alw, wh_ids) -> bool:
    if alw is not None and w.get("division_id") and w["division_id"] not in alw:
        return False
    return not wh_ids or w["id"] in wh_ids


async def stock_aggregate(server, wh_ids: list, user) -> dict:
    """{item_id: (total, min_total, max_total, records, value, unvalued_pools)} untuk gudang scope; dihitung di database.
    `value` = SUM(total_value) apa adanya dari engine MWA (read-only); `unvalued_pools` = pool `missing_average`."""
    if not wh_ids:
        return {}
    if server.DB_BACKEND == "mariadb":
        import tenant_foundation_layer as TF
        import tenant_isolation_layer as TI
        raw = server.client[os.environ.get("DB_NAME", "default")]
        await raw._ensure_table("item_warehouse")
        tenant = TI.current_tenant_id() or TF.tenant_id_of(user)
        marks = ", ".join(["%s"] * len(wh_ids))
        sql = ("SELECT item_id, SUM(COALESCE(CAST(current_stock AS DOUBLE), 0)), "
               "SUM(COALESCE(CAST(min_stock AS DOUBLE), 0)), SUM(COALESCE(CAST(max_stock AS DOUBLE), 0)), COUNT(*), "
               "SUM(COALESCE(CAST(JSON_VALUE(doc, '$.total_value') AS DOUBLE), 0)), "
               "SUM(CASE WHEN COALESCE(CAST(current_stock AS DOUBLE), 0) > 0.000001 "
               "AND COALESCE(CAST(JSON_VALUE(doc, '$.avg_cost') AS DOUBLE), 0) <= 0 THEN 1 ELSE 0 END) "
               f"FROM `item_warehouse` WHERE tenant_id = %s AND warehouse_id IN ({marks}) GROUP BY item_id")
        rows = await raw._fetchall(sql, [tenant, *wh_ids])
        return {r[0]: (float(r[1] or 0), float(r[2] or 0), float(r[3] or 0), int(r[4] or 0), float(r[5] or 0), int(r[6] or 0))
                for r in rows if r[0]}
    out = {}
    for iw in await server.db.item_warehouse.find({"warehouse_id": {"$in": wh_ids}}, {"_id": 0}).to_list(None):
        if not iw.get("item_id"):
            continue
        t = out.get(iw["item_id"], (0.0, 0.0, 0.0, 0, 0.0, 0))
        out[iw["item_id"]] = (t[0] + _f(iw.get("current_stock")), t[1] + _f(iw.get("min_stock")), t[2] + _f(iw.get("max_stock")),
                              t[3] + 1, t[4] + _f(iw.get("total_value")),
                              t[5] + (1 if missing_average(iw.get("current_stock"), iw.get("avg_cost")) else 0))
    return out


def summarize(rows: list) -> dict:
    """out_of_stock mencakup barang tanpa catatan stok; no_stock = bagian dari out_of_stock (informasi)."""
    summary = {"total": len(rows), "out_of_stock": 0, "low_stock": 0, "overstock": 0, "normal": 0, "no_stock": 0}
    for r in rows:
        summary[SUMMARY_KEY[r["stock_status"]]] += 1
        if not r["stock_records"]:
            summary["no_stock"] += 1
    return summary


async def compute(server, user, *, warehouse_id: str = "", division_id: str = "", category_id: str = "",
                  active: str = "", q: str = "", with_value: bool = False, value_as_of: Optional[str] = None) -> dict:
    """Baris per Master Item (sudah di-scope & difilter) + ringkasan canonical.
    active: "" = semua, "Aktif", "Nonaktif". Raise 403 bila gudang/divisi di luar cakupan."""
    alw, wh_assigned = allowed(server, user), assigned_warehouses(server, user)
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

    warehouse_id, division_id, category_id = (warehouse_id or "").strip(), (division_id or "").strip(), (category_id or "").strip()
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
    items_raw, agg = await asyncio.gather(db.items.find(flt, ITEM_PROJECTION).to_list(100000), stock_aggregate(server, col_ids, user))

    terms = (q or "").strip().lower().split()
    rows, value, unvalued, val_ids = [], 0.0, 0, set()
    for it in items_raw:
        if not it.get("id") or not item_in_scope(it, alw):
            continue
        a = agg.get(it["id"])
        if warehouse_id and not a:
            continue  # filter gudang = barang yang memiliki catatan stok di gudang tsb (rule existing)
        if terms:
            hay = " ".join(str(it.get(k) or "") for k in ("code", "name", "alias", "part_number", "brand")).lower()
            if not all(t in hay for t in terms):
                continue
        total, mn, mx, n, val, unv = a or (0.0, 0.0, 0.0, 0, 0.0, 0)
        # Nilai Persediaan = seluruh carrying value dalam scope, TERMASUK barang nonaktif yang masih bersaldo
        # (filter status aktif hanya untuk KPI jumlah/status stok).
        val_ids.add(it["id"])
        value += val
        unvalued += 1 if unv else 0
        if active == "Aktif" and not it.get("is_active"):
            continue
        if active == "Nonaktif" and it.get("is_active"):
            continue
        names = [div_name.get(d) or "-" for d in _item_divisions(it) if alw is None or d in alw]
        rows.append({**it,
                     "category_label": cat_name.get(it.get("category_id")) or it.get("category") or None,
                     "division_label": ", ".join(names) if names else None,
                     "unit_label": uom_label.get(it.get("base_uom_id")) or it.get("unit") or None,
                     "status_label": "Aktif" if it.get("is_active") else "Nonaktif",
                     "total_stock": round(total, 6), "stock_records": n,
                     "stock_status": item_status(total, mn, mx, n)})
    out = {"rows": rows, "summary": summarize(rows), "col_whs": col_whs, "scoped_whs": scoped_whs,
           "divisions": divs, "categories": cats, "alw": alw, "warehouse_count": len(col_ids)}
    if with_value:
        today = today_iso()
        as_of = value_as_of if value_as_of and value_as_of < today else None
        if as_of is None:  # periode berakhir hari ini / masa depan -> posisi valuation saat ini (= Valuation Summary / reconcile)
            out["inventory_value"], out["unvalued_items"] = round(value, 4), unvalued
            out["unreconstructable_items"] = out["unreconstructable_pools"] = 0
        else:  # historis -> posisi valuation ledger per tanggal akhir filter (nilai & "belum bernilai" pada tanggal sama)
            (out["inventory_value"], out["unvalued_items"], out["unreconstructable_items"],
             out["unreconstructable_pools"]) = await value_as_of_fn(server, val_ids, col_ids, as_of)
        out["inventory_value_as_of"] = as_of or today
    return out


async def list_response(server, user, qp: dict, *, force_active: Optional[str] = None) -> dict:
    """Response list per item (pagination/sort/sel per gudang) — dipakai Master Barang & Inventory."""
    size, page = _size(qp.get("page_size")), _page(qp.get("page"))
    res = await compute(server, user, warehouse_id=qp.get("warehouse_id") or "", division_id=qp.get("division_id") or "",
                        category_id=qp.get("category_id") or "",
                        active=force_active if force_active is not None else (qp.get("active") or ""), q=qp.get("q") or "")
    rows, summary, col_whs, scoped_whs, alw = res["rows"], res["summary"], res["col_whs"], res["scoped_whs"], res["alw"]

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
    col_ids = [w["id"] for w in col_whs]
    cells = {}
    if page_rows and col_ids:
        iws = await server.db.item_warehouse.find(
            {"item_id": {"$in": [r["id"] for r in page_rows]}, "warehouse_id": {"$in": col_ids}},
            {"_id": 0, "item_id": 1, "warehouse_id": 1, "current_stock": 1, "min_stock": 1, "max_stock": 1}).to_list(None)
        for iw in iws:
            cur = _f(iw.get("current_stock"))
            cells.setdefault(iw["item_id"], {})[iw["warehouse_id"]] = {
                "qty": cur, "min": _f(iw.get("min_stock")), "max": _f(iw.get("max_stock")),
                "status": cell_status(cur, iw.get("min_stock"), iw.get("max_stock"))}
    for r in page_rows:
        r["stock"] = cells.get(r["id"], {})

    div_opts = [{"id": d["id"], "name": d.get("name")} for d in res["divisions"]
                if d.get("id") and d.get("is_active") is not False and (alw is None or d["id"] in alw)]
    div_opts.sort(key=lambda d: str(d.get("name") or "").lower())
    cat_opts = sorted([{"id": c["id"], "name": c.get("name")} for c in res["categories"] if c.get("id") and c.get("is_active") is not False],
                      key=lambda c: str(c.get("name") or "").lower())
    return {"items": page_rows, "total": total, "page": page, "page_size": size, "summary": summary,
            "warehouses": [{"id": w["id"], "code": w.get("code"), "name": w.get("name")} for w in col_whs],
            "filters": {"warehouses": [{"id": w["id"], "code": w.get("code"), "name": w.get("name")} for w in scoped_whs],
                        "divisions": div_opts, "categories": cat_opts}}


def dashboard_stock(summary: dict) -> dict:
    """Bentuk blok `stock` dashboard (key lama dipertahankan) dari ringkasan canonical."""
    return {k: summary.get(k, 0) for k in ("total", "out_of_stock", "low_stock", "overstock", "normal", "no_stock")}
