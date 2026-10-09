"""P1 — Laporan Persediaan & Nilai Persediaan pada Pusat Laporan (READ-ONLY).

Sumber data (tanpa formula harga baru; engine/formula MWA, transaksi, dan data historis tidak diubah):
  - Qty mutasi      : `stock_ledger` (seluruh mutasi qty, termasuk Opening Balance Import).
  - Nilai (MWA)     : `valuation_ledger` (value_in / value_out / value_after hasil engine `server.post_movement`).
  - Posisi hari ini : `item_warehouse` (current_stock, total_value, avg_cost, min_stock, max_stock) = Inventory/Dashboard.
  - Posisi historis : qty = Σ mutasi stock_ledger s/d cut-off; nilai = value_after entri valuation_ledger TERAKHIR per
                      item×gudang s/d cut-off (= `stock_summary.value_as_of_fn` / Inventory per tanggal).
  - Tanggal efektif : tanggal bisnis WIB dari `txn_at` (fallback `at`) — sama dengan P0 valuation-ledger & Inventory.
Scope = `stock_summary.compute` (tenant, cakupan divisi barang, gudang aktif dalam cakupan + penugasan gudang,
filter gudang/divisi/kategori) -> total identik dengan Inventory/Dashboard pada scope & cut-off yang sama.
Mutasi internal (Transfer/Loan/Loan Return) tampil sebagai kolom Masuk & Keluar terpisah; pada cakupan seluruh gudang
keduanya saling meniadakan sehingga saldo total perusahaan tidak berganda.
Identitas per baris: Saldo Awal + Σ mutasi + Selisih = Saldo Akhir (Selisih = koreksi pool di luar mutasi tercatat,
mis. pembulatan saldo nol / revaluasi saldo awal; normalnya 0).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi import HTTPException

import stock_summary as SS
from reporting.registry import Column, Filter, ReportSpec, register
from reporting.scope import local_day

G = "persediaan"
TOL = 1e-6

# Kategori mutasi (doc_type existing; "Reversal X" = kategori X dengan arah terbalik)
CATS = (("do", "Penerimaan DO"), ("mi", "Pemakaian MI"), ("tl_in", "Transfer/Loan Masuk"),
        ("tl_out", "Transfer/Loan Keluar"), ("adj", "Adjustment"), ("opn", "Stock Opname"), ("opening", "Saldo Awal"),
        ("other", "Lainnya"))
CAT_OF = {"DO": "do", "MI": "mi", "Transfer In": "tl_in", "Loan In": "tl_in", "Loan Return In": "tl_in",
          "Transfer Out": "tl_out", "Loan Out": "tl_out", "Loan Return Out": "tl_out", "Stock Adjustment": "adj",
          "Stock Opname Adjustment": "opn", "Opening Balance": "opening", "Opening Balance Import": "opening",
          "Opening Valuation": "opening"}
OUTWARD = {"mi", "tl_out"}  # ditampilkan positif sebagai pengeluaran
STATUS_LABEL = {"Out of Stock": "Kosong", "Low Stock": "Di bawah Min", "Normal": "Normal", "Overstock": "Di atas Max"}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def cat_of(doc_type) -> str:
    t = str(doc_type or "")
    if t.startswith("Reversal "):
        t = t[len("Reversal "):]
    return CAT_OF.get(t, "other")


def eff_day(r) -> str:
    return local_day(r.get("txn_at") or r.get("at"))


def prev_day(d: str) -> str:
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


# ----------------------------------------------------------------------------------------------- scope & data
async def scope(server, user, p) -> dict:
    """Barang & gudang dalam cakupan (aturan Inventory). Barang/gudang di luar cakupan -> 403."""
    c = await SS.compute(server, user, warehouse_id=p.get("warehouse_id") or "", division_id=p.get("division_id") or "",
                         category_id=p.get("category_id") or "")
    items = {r["id"]: r for r in c["rows"]}
    if p.get("item_id"):
        it = await server.db.items.find_one({"id": p["item_id"]}, {"_id": 0})
        if not it:
            raise HTTPException(404, "Barang tidak ditemukan.")
        if not SS.item_in_scope(it, c["alw"]):
            raise HTTPException(403, "Barang ini berada di luar cakupan divisi Anda.")
        items = {k: v for k, v in items.items() if k == p["item_id"]}
    whs = {w["id"]: w for w in c["col_whs"]}
    divs = {d["id"]: d.get("name") for d in c["divisions"] if d.get("id")}
    return {"items": items, "whs": whs, "divs": divs, "today": SS.today_iso()}


async def _rows(server, coll, sc, extra=None):
    if not sc["items"] or not sc["whs"]:
        return []
    q = {"warehouse_id": {"$in": sorted(sc["whs"])}}
    if len(sc["items"]) == 1:
        q["item_id"] = next(iter(sc["items"]))
    q.update(extra or {})
    rows = await getattr(server.db, coll).find(q, {"_id": 0}).to_list(None)
    out = [r for r in rows if r.get("item_id") in sc["items"]]
    for r in out:
        r["_day"] = eff_day(r)
    out.sort(key=lambda r: (r["_day"], str(r.get("at") or "")))
    return out


async def pools_now(server, sc) -> dict:
    if not sc["items"] or not sc["whs"]:
        return {}
    rows = await server.db.item_warehouse.find({"warehouse_id": {"$in": sorted(sc["whs"])}}, {"_id": 0}).to_list(None)
    return {(r["item_id"], r["warehouse_id"]): r for r in rows if r.get("item_id") in sc["items"]}


def qty_at(srows, pools, d, today) -> dict:
    """Qty per pool pada akhir hari `d` (WIB). d None -> {} (belum ada saldo); d >= hari ini -> item_warehouse."""
    if d is None:
        return {}
    if d >= today:
        return {k: _f(v.get("current_stock")) for k, v in pools.items()}
    out = {}
    for r in srows:
        if r["_day"] > d:
            break
        k = (r["item_id"], r.get("warehouse_id"))
        out[k] = out.get(k, 0.0) + _f(r.get("qty_in")) - _f(r.get("qty_out"))
    return out


def value_at(vrows, pools, d, today) -> tuple:
    """(nilai per pool, pool belum dapat direkonstruksi) pada akhir hari `d` — semantik `value_as_of_fn` Inventory."""
    if d is None:
        return {}, set()
    if d >= today:
        return {k: _f(v.get("total_value")) for k, v in pools.items()}, set()
    last, first = {}, {}
    for r in vrows:
        k = (r["item_id"], r.get("warehouse_id"))
        first.setdefault(k, r)
        if r["_day"] <= d:
            last[k] = r
    unknown = {k for k, r in first.items() if k not in last and _f(r.get("qty_before")) > TOL}
    unknown |= {k for k, v in pools.items() if k not in first and _f(v.get("current_stock")) > TOL}
    return {k: _f(r.get("value_after")) for k, r in last.items()}, unknown


def _item_cols(sc, k):
    it, w = sc["items"].get(k[0], {}), sc["whs"].get(k[1], {})
    return {"item_id": k[0], "warehouse_id": k[1], "item_code": it.get("code"), "item_name": it.get("name"),
            "category": it.get("category_label"), "unit": it.get("unit_label"), "warehouse": w.get("name"),
            "warehouse_division": sc["divs"].get(w.get("division_id")) or "-"}


def _sort(rows):
    rows.sort(key=lambda r: (str(r.get("item_name") or "").lower(), str(r.get("item_code") or ""), str(r.get("warehouse") or "")))
    return rows


# ----------------------------------------------------------------------------------------------- 1. posisi stok
async def posisi_stok(server, user, p):
    sc = await scope(server, user, p)
    d = p.get("as_of") or sc["today"]
    pools, srows, vrows = await asyncio.gather(pools_now(server, sc), _rows(server, "stock_ledger", sc),
                                               _rows(server, "valuation_ledger", sc))
    qty = qty_at(srows, pools, d, sc["today"])
    val, unknown = value_at(vrows, pools, d, sc["today"])
    out = []
    for k in set(qty) | set(val) | set(pools):
        q, v = qty.get(k, 0.0), val.get(k, 0.0)
        if p.get("show_zero") != "1" and abs(q) <= TOL and abs(v) <= TOL:
            continue
        pool = pools.get(k, {})
        out.append({**_item_cols(sc, k), "qty": round(q, 6), "min_stock": _f(pool.get("min_stock")),
                    "max_stock": _f(pool.get("max_stock")),
                    "status": STATUS_LABEL[SS.cell_status(q, pool.get("min_stock"), pool.get("max_stock"))],
                    "avg_cost": round(v / q, 6) if q > TOL else 0.0, "value": round(v, 4),
                    "note": "Riwayat nilai sebelum tanggal ini tidak tersedia" if k in unknown else ""})
    return _sort(out)


# ----------------------------------------------------------------------------------------------- 2. ringkasan nilai
GROUP_BY = (("warehouse", "Gudang"), ("division", "Divisi Gudang"), ("category", "Kategori Barang"))


async def ringkasan_nilai(server, user, p):
    sc = await scope(server, user, p)
    d = p.get("as_of") or sc["today"]
    pools, vrows = await asyncio.gather(pools_now(server, sc), _rows(server, "valuation_ledger", sc))
    val, _ = value_at(vrows, pools, d, sc["today"])
    gb = p.get("group_by") or "warehouse"
    grp = {}
    for k, v in val.items():
        if abs(v) <= TOL:
            continue
        it, w = sc["items"].get(k[0], {}), sc["whs"].get(k[1], {})
        if gb == "warehouse":
            gk, code, name = k[1], w.get("code"), w.get("name")
        elif gb == "division":
            gk, code, name = w.get("division_id") or "-", "", sc["divs"].get(w.get("division_id")) or "(Tanpa Divisi)"
        else:
            gk, code, name = it.get("category_id") or "-", "", it.get("category_label") or "(Tanpa Kategori)"
        g = grp.setdefault(gk, {"group_code": code or "", "group_name": name or "-", "items": set(), "pools": 0, "value": 0.0})
        g["items"].add(k[0]); g["pools"] += 1; g["value"] += v
    total = sum(g["value"] for g in grp.values())
    out = [{"group_code": g["group_code"], "group_name": g["group_name"], "item_count": len(g["items"]),
            "pool_count": g["pools"], "value": round(g["value"], 4),
            "share": round(g["value"] / total * 100, 2) if total else 0.0} for g in grp.values()]
    out.sort(key=lambda r: -r["value"])
    return out


# ----------------------------------------------------------------------------------------------- 3/4. kartu stok
def _in_period(r, p):
    return (not p.get("date_from") or r["_day"] >= p["date_from"]) and (not p.get("date_to") or r["_day"] <= p["date_to"])


async def kartu_qty(server, user, p):
    sc = await scope(server, user, p)
    pools, srows = await asyncio.gather(pools_now(server, sc), _rows(server, "stock_ledger", sc))
    start = prev_day(p["date_from"]) if p.get("date_from") else None
    end = p.get("date_to") or sc["today"]
    open_q = sum(qty_at(srows, pools, start, sc["today"]).values()) if start else 0.0
    close_q = sum(qty_at(srows, pools, end, sc["today"]).values())
    bal, out = open_q, [{"_kind": "opening", "txn_date": p.get("date_from") or "", "doc_type": "Saldo Awal", "balance": round(open_q, 6)}]
    for r in srows:
        if not _in_period(r, p):
            continue
        qi, qo = _f(r.get("qty_in")), _f(r.get("qty_out"))
        bal += qi - qo
        out.append({"txn_date": r["_day"], "doc_type": r.get("doc_type"), "doc_no": r.get("doc_no"),
                    "warehouse": sc["whs"].get(r.get("warehouse_id"), {}).get("name"), "qty_in": qi, "qty_out": qo,
                    "balance": round(bal, 6), "category": dict(CATS)[cat_of(r.get("doc_type"))]})
    diff = close_q - bal
    out.append({"_kind": "closing", "txn_date": end, "doc_type": "Saldo Akhir", "balance": round(close_q, 6),
                "note": f"Selisih pool {round(diff, 6)}" if abs(diff) > TOL else ""})
    return out


async def kartu_nilai(server, user, p):
    sc = await scope(server, user, p)
    pools, vrows = await asyncio.gather(pools_now(server, sc), _rows(server, "valuation_ledger", sc))
    start = prev_day(p["date_from"]) if p.get("date_from") else None
    end = p.get("date_to") or sc["today"]
    open_v = value_at(vrows, pools, start, sc["today"])[0] if start else {}
    close_v = value_at(vrows, pools, end, sc["today"])[0]
    pool_v = dict(open_v)
    pool_q = {}
    if start:
        for r in vrows:
            if r["_day"] <= start:
                pool_q[(r["item_id"], r.get("warehouse_id"))] = _f(r.get("qty_after"))
    tv, tq = sum(pool_v.values()), sum(pool_q.values())
    out = [{"_kind": "opening", "txn_date": p.get("date_from") or "", "doc_type": "Saldo Awal",
            "balance_qty": round(tq, 6), "balance_value": round(tv, 4), "avg": round(tv / tq, 6) if tq > TOL else 0.0}]
    for r in vrows:
        if not _in_period(r, p):
            continue
        k = (r["item_id"], r.get("warehouse_id"))
        vi, vo = _f(r.get("value_in")), _f(r.get("value_out"))
        delta = _f(r.get("value_after")) - pool_v.get(k, 0.0)
        pool_v[k] = _f(r.get("value_after"))
        tq += _f(r.get("qty_after")) - pool_q.get(k, 0.0)
        pool_q[k] = _f(r.get("qty_after"))
        tv += delta
        out.append({"txn_date": r["_day"], "doc_type": r.get("doc_type"), "doc_no": r.get("doc_no"),
                    "warehouse": sc["whs"].get(r.get("warehouse_id"), {}).get("name"),
                    "qty_in": _f(r.get("qty_in")), "qty_out": _f(r.get("qty_out")), "unit_cost": _f(r.get("unit_cost")),
                    "value_in": vi, "value_out": vo, "value_diff": round(delta - (vi - vo), 4),
                    "balance_qty": round(tq, 6), "balance_value": round(tv, 4),
                    "avg": round(tv / tq, 6) if tq > TOL else 0.0})
    cv = sum(close_v.values())
    diff = cv - tv
    out.append({"_kind": "closing", "txn_date": end, "doc_type": "Saldo Akhir", "balance_qty": round(tq, 6),
                "balance_value": round(cv, 4), "value_diff": round(diff, 4) if abs(diff) > 1e-4 else 0.0,
                "avg": round(cv / tq, 6) if tq > TOL else 0.0})
    return out


# ----------------------------------------------------------------------------------------------- 5. mutasi
def _signed(cat, net):
    return (-net if cat in OUTWARD else net) + 0.0  # + 0.0: tanpa "-0"


async def mutasi(server, user, p):
    sc = await scope(server, user, p)
    pools, srows, vrows = await asyncio.gather(pools_now(server, sc), _rows(server, "stock_ledger", sc),
                                               _rows(server, "valuation_ledger", sc))
    start = prev_day(p["date_from"]) if p.get("date_from") else None
    end = p.get("date_to") or sc["today"]
    q0, q1 = qty_at(srows, pools, start, sc["today"]), qty_at(srows, pools, end, sc["today"])
    v0, v1 = value_at(vrows, pools, start, sc["today"])[0], value_at(vrows, pools, end, sc["today"])[0]
    mq, mv = {}, {}
    for rows, acc, a, b in ((srows, mq, "qty_in", "qty_out"), (vrows, mv, "value_in", "value_out")):
        for r in rows:
            if _in_period(r, p):
                k = (r["item_id"], r.get("warehouse_id"))
                c = cat_of(r.get("doc_type"))
                acc.setdefault(k, {})[c] = acc.setdefault(k, {}).get(c, 0.0) + _f(r.get(a)) - _f(r.get(b))
    out = []
    for k in set(q0) | set(q1) | set(v0) | set(v1) | set(mq) | set(mv):
        a_q, z_q, a_v, z_v = q0.get(k, 0.0), q1.get(k, 0.0), v0.get(k, 0.0), v1.get(k, 0.0)
        if not mq.get(k) and not mv.get(k) and max(abs(a_q), abs(z_q), abs(a_v), abs(z_v)) <= TOL:
            continue
        row = {**_item_cols(sc, k), "q_open": round(a_q, 6), "q_close": round(z_q, 6), "v_open": round(a_v, 4),
               "v_close": round(z_v, 4)}
        nq = nv = 0.0
        for c, _ in CATS:
            x, y = mq.get(k, {}).get(c, 0.0), mv.get(k, {}).get(c, 0.0)
            nq += x; nv += y
            row[f"q_{c}"], row[f"v_{c}"] = round(_signed(c, x), 6) + 0.0, round(_signed(c, y), 4) + 0.0
        row["q_diff"] = round(z_q - a_q - nq, 6) if abs(z_q - a_q - nq) > TOL else 0.0
        row["v_diff"] = round(z_v - a_v - nv, 4) if abs(z_v - a_v - nv) > 1e-4 else 0.0
        out.append(row)
    return _sort(out)


# ----------------------------------------------------------------------------------------------- 6. HPP MI
HPP_GROUP = (("project", "Proyek"), ("unit", "Unit"), ("spk", "SPK"), ("item", "Barang"))


async def hpp_mi(server, user, p):
    sc = await scope(server, user, p)
    vrows = [r for r in await _rows(server, "valuation_ledger", sc) if cat_of(r.get("doc_type")) == "mi" and _in_period(r, p)]
    if p.get("project_id"):
        vrows = [r for r in vrows if r.get("project_id") == p["project_id"]]
    if p.get("unit_id"):
        vrows = [r for r in vrows if r.get("unit_id") == p["unit_id"]]
    gb = p.get("group_by") or "project"
    db = server.db
    names = {}
    for coll, key in (("projects", "project"), ("units", "unit"), ("spk", "spk")):
        names[key] = {x["id"]: x for x in await getattr(db, coll).find({}, {"_id": 0}).to_list(None) if x.get("id")}
    allocs = {}
    if gb == "spk":
        line_ids = sorted({r.get("line_id") for r in vrows if r.get("line_id")})
        if line_ids:
            for a in await db.procurement_item_spk_allocations.find({"source_type": "mi", "item_line_id": {"$in": line_ids}},
                                                                     {"_id": 0}).to_list(None):
                allocs.setdefault(a.get("item_line_id"), []).append(a)
    grp = {}

    def add(gk, code, name, r, qty, hpp):
        g = grp.setdefault(gk, {"group_code": code or "", "group_name": name or "-", "docs": set(), "lines": 0, "qty": 0.0, "hpp": 0.0})
        g["docs"].add(r.get("doc_id")); g["lines"] += 1; g["qty"] += qty; g["hpp"] += hpp

    for r in vrows:
        qty, hpp = _f(r.get("qty_out")) - _f(r.get("qty_in")), _f(r.get("value_out")) - _f(r.get("value_in"))
        if gb in ("project", "unit"):
            x = names[gb].get(r.get(f"{gb}_id"))
            add(r.get(f"{gb}_id") or "-", (x or {}).get("code"), (x or {}).get("name") or f"(Tanpa {dict(HPP_GROUP)[gb]})", r, qty, hpp)
        elif gb == "item":
            it = sc["items"].get(r["item_id"], {})
            add(r["item_id"], it.get("code"), it.get("name"), r, qty, hpp)
        else:  # SPK: bagi HPP baris MI per porsi qty alokasi SPK (rumus existing /mi/{id}/valuation)
            al = allocs.get(r.get("line_id")) or []
            tot = sum(_f(a.get("allocated_qty")) for a in al)
            if tot <= 0:
                add("-", "", "(Tanpa SPK)", r, qty, hpp)
                continue
            for a in al:
                share = _f(a.get("allocated_qty")) / tot
                s = names["spk"].get(a.get("spk_id")) or {}
                add(a.get("spk_id"), s.get("no") or s.get("spk_no") or s.get("number"), s.get("name") or s.get("title") or s.get("job_name"),
                    r, qty * share, round(hpp * share, 4))
    total = sum(g["hpp"] for g in grp.values())
    out = [{"group_code": g["group_code"], "group_name": g["group_name"], "doc_count": len(g["docs"]), "line_count": g["lines"],
            "qty": round(g["qty"], 6), "hpp": round(g["hpp"], 4), "share": round(g["hpp"] / total * 100, 2) if total else 0.0}
           for g in grp.values()]
    out.sort(key=lambda r: -r["hpp"])
    return out


# ----------------------------------------------------------------------------------------------- 7. min/max
MM_STATUS = tuple((v, v) for v in ("Kosong", "Di bawah Min", "Normal", "Di atas Max"))


def reorder_qty(cur, mn, mx) -> float:
    """Saran reorder (disetujui user): Max − stok; bila Max kosong, Min − stok; hanya untuk Kosong / Di bawah Min."""
    st = STATUS_LABEL[SS.cell_status(cur, mn, mx)]
    if st not in ("Kosong", "Di bawah Min"):
        return 0.0
    target = _f(mx) if _f(mx) > 0 else _f(mn)
    return round(max(0.0, target - _f(cur)), 6)


async def min_max(server, user, p):
    sc = await scope(server, user, p)
    pools = await pools_now(server, sc)
    out = []
    for k, pool in pools.items():
        cur, mn, mx = _f(pool.get("current_stock")), _f(pool.get("min_stock")), _f(pool.get("max_stock"))
        st = STATUS_LABEL[SS.cell_status(cur, mn, mx)]
        if p.get("status") and st != p["status"]:
            continue
        rq = reorder_qty(cur, mn, mx)
        if p.get("need") == "reorder" and rq <= TOL:
            continue
        out.append({**_item_cols(sc, k), "qty": round(cur, 6), "min_stock": mn, "max_stock": mx, "status": st, "reorder": rq})
    return _sort(out)


# ----------------------------------------------------------------------------------------------- registrasi
F_ASOF = Filter("as_of", "Per Tanggal (cut-off)", "date")
F_FROM, F_TO = Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date")
F_DIV, F_WH = Filter("division_id", "Divisi", "division"), Filter("warehouse_id", "Gudang", "warehouse")
F_CAT, F_ITEM = Filter("category_id", "Kategori", "category"), Filter("item_id", "Barang", "item")
F_ITEM_REQ = Filter("item_id", "Barang", "item", required=True)
SCOPE_NOTE = ("Cakupan = aturan Inventory (divisi barang, gudang aktif dalam cakupan). ")
ITEM_COLS = (Column("item_code", "Kode Barang", width=14), Column("item_name", "Nama Barang", width=26),
             Column("category", "Kategori", width=16), Column("unit", "Satuan", width=9),
             Column("warehouse", "Gudang", width=18))
ITEM_SEARCH = ("item_code", "item_name", "category", "warehouse")

register(ReportSpec(
    key="posisi-stok", group=G, title="Posisi Stok per Barang × Gudang",
    description="Qty, rata-rata biaya (MWA), dan nilai persediaan per barang per gudang pada tanggal cut-off.",
    date_basis=SCOPE_NOTE + "Cut-off = akhir hari tanggal bisnis WIB; kosong = hari ini (posisi pool saat ini).",
    builder=posisi_stok,
    columns=ITEM_COLS + (Column("warehouse_division", "Divisi Gudang", width=14),
                         Column("qty", "Qty", "qty", total=True, width=11),
                         Column("min_stock", "Min", "qty", width=9), Column("max_stock", "Max", "qty", width=9),
                         Column("status", "Status Stok", width=12),
                         Column("avg_cost", "Rata-rata Biaya", "money", price=True, width=14),
                         Column("value", "Nilai Persediaan", "money", price=True, total=True, width=16),
                         Column("note", "Keterangan", width=20)),
    filters=(F_ASOF, F_DIV, F_WH, F_CAT, F_ITEM, Filter("show_zero", "Saldo Nol", "select", (("1", "Tampilkan saldo nol"),))),
    search_keys=ITEM_SEARCH,
))

register(ReportSpec(
    key="ringkasan-nilai", group=G, title="Ringkasan Nilai Persediaan",
    description="Nilai persediaan (valuation ledger MWA) per Gudang, Divisi Gudang, atau Kategori pada tanggal cut-off.",
    date_basis=SCOPE_NOTE + "Cut-off = akhir hari WIB; kosong = hari ini. Total = Nilai Persediaan Inventory/Dashboard.",
    builder=ringkasan_nilai, permission="view_purchase_price",
    columns=(Column("group_code", "Kode", width=12), Column("group_name", "Kelompok", width=28),
             Column("item_count", "Jumlah Barang", "int", total=True, width=12),
             Column("pool_count", "Jumlah Barang×Gudang", "int", total=True, width=14),
             Column("value", "Nilai Persediaan", "money", price=True, total=True, width=18),
             Column("share", "Porsi (%)", "qty", total=True, width=10)),
    filters=(F_ASOF, Filter("group_by", "Kelompokkan", "select", GROUP_BY, default="warehouse"), F_DIV, F_WH, F_CAT),
    search_keys=("group_code", "group_name"),
))

register(ReportSpec(
    key="kartu-stok-qty", group=G, title="Kartu Stok (Qty)",
    description="Saldo awal, mutasi kronologis dengan saldo berjalan, dan saldo akhir qty untuk 1 barang.",
    date_basis=SCOPE_NOTE + "Tanggal transaksi bisnis WIB, inklusif. Tanpa gudang = seluruh gudang dalam cakupan.",
    builder=kartu_qty,
    columns=(Column("txn_date", "Tanggal", "date", width=11), Column("doc_type", "Jenis Transaksi", width=20),
             Column("category", "Kelompok Mutasi", width=16), Column("doc_no", "No. Dokumen", width=20),
             Column("warehouse", "Gudang", width=18), Column("qty_in", "Masuk", "qty", total=True, width=11),
             Column("qty_out", "Keluar", "qty", total=True, width=11), Column("balance", "Saldo", "qty", width=12),
             Column("note", "Keterangan", width=16)),
    filters=(F_ITEM_REQ, F_WH, F_FROM, F_TO), search_keys=("doc_type", "doc_no", "warehouse"),
))

register(ReportSpec(
    key="kartu-stok-nilai", group=G, title="Kartu Stok (Nilai MWA)",
    description="Mutasi nilai per transaksi dari valuation ledger (MWA): harga satuan, nilai masuk/keluar, saldo berjalan.",
    date_basis=SCOPE_NOTE + "Tanggal transaksi bisnis WIB, inklusif. Saldo akhir = Nilai Persediaan Inventory per tanggal.",
    builder=kartu_nilai, permission="view_purchase_price",
    columns=(Column("txn_date", "Tanggal", "date", width=11), Column("doc_type", "Jenis Transaksi", width=20),
             Column("doc_no", "No. Dokumen", width=20), Column("warehouse", "Gudang", width=16),
             Column("qty_in", "Qty Masuk", "qty", total=True, width=10), Column("qty_out", "Qty Keluar", "qty", total=True, width=10),
             Column("unit_cost", "Harga Satuan", "money", price=True, width=13),
             Column("value_in", "Nilai Masuk", "money", price=True, total=True, width=14),
             Column("value_out", "Nilai Keluar", "money", price=True, total=True, width=14),
             Column("value_diff", "Selisih Nilai", "money", price=True, total=True, width=12),
             Column("balance_qty", "Saldo Qty", "qty", width=11),
             Column("balance_value", "Saldo Nilai", "money", price=True, width=15),
             Column("avg", "Rata-rata", "money", price=True, width=13)),
    filters=(F_ITEM_REQ, F_WH, F_FROM, F_TO), search_keys=("doc_type", "doc_no", "warehouse"),
))

_MUT = []
for _c, _lb in CATS:
    _MUT.append(Column(f"q_{_c}", f"Qty {_lb}", "qty", total=True, width=10))
_MUTV = [Column(f"v_{_c}", f"Nilai {_lb}", "money", price=True, total=True, width=13) for _c, _lb in CATS]
register(ReportSpec(
    key="mutasi-persediaan", group=G, title="Mutasi Persediaan",
    description="Saldo awal, mutasi per jenis transaksi (DO, MI, Transfer/Loan, Adjustment, Opname, Saldo Awal), dan saldo "
                "akhir per barang × gudang. Transfer/Loan internal saling meniadakan pada cakupan seluruh gudang.",
    date_basis=SCOPE_NOTE + "Periode = tanggal transaksi bisnis WIB, inklusif. Saldo Awal + Mutasi + Selisih = Saldo Akhir.",
    builder=mutasi,
    columns=ITEM_COLS + (Column("q_open", "Qty Saldo Awal", "qty", total=True, width=11), *_MUT,
                         Column("q_diff", "Qty Selisih", "qty", total=True, width=9),
                         Column("q_close", "Qty Saldo Akhir", "qty", total=True, width=11),
                         Column("v_open", "Nilai Saldo Awal", "money", price=True, total=True, width=14), *_MUTV,
                         Column("v_diff", "Nilai Selisih", "money", price=True, total=True, width=12),
                         Column("v_close", "Nilai Saldo Akhir", "money", price=True, total=True, width=14)),
    filters=(F_FROM, F_TO, F_DIV, F_WH, F_CAT, F_ITEM), search_keys=ITEM_SEARCH,
))

register(ReportSpec(
    key="hpp-mi", group=G, title="Rekap HPP Pemakaian Barang (MI)",
    description="HPP pemakaian barang dari nilai keluar MI pada valuation ledger (net reversal), per Proyek/Unit/SPK/Barang.",
    date_basis=SCOPE_NOTE + "Periode = tanggal MI bisnis WIB, inklusif. SPK: HPP dibagi menurut porsi qty alokasi SPK.",
    builder=hpp_mi, permission="view_purchase_price",
    columns=(Column("group_code", "Kode", width=14), Column("group_name", "Kelompok", width=28),
             Column("doc_count", "Jumlah MI", "int", width=10), Column("line_count", "Baris MI", "int", total=True, width=10),
             Column("qty", "Qty Pemakaian", "qty", total=True, width=12),
             Column("hpp", "HPP Pemakaian", "money", price=True, total=True, width=18),
             Column("share", "Porsi (%)", "qty", total=True, width=10)),
    filters=(F_FROM, F_TO, Filter("group_by", "Kelompokkan", "select", HPP_GROUP, default="project"), F_DIV, F_WH, F_CAT,
             Filter("project_id", "Proyek", "project"), Filter("unit_id", "Unit", "unit")),
    search_keys=("group_code", "group_name"),
))

register(ReportSpec(
    key="min-max-reorder", group=G, title="Min/Max, Stok Menipis & Reorder",
    description="Stok saat ini vs Min/Max per barang × gudang, status stok, dan saran qty reorder.",
    date_basis=SCOPE_NOTE + "Posisi saat ini. Status: Kosong (≤0), Di bawah Min (≤ Min), Normal, Di atas Max. "
                            "Saran reorder = Max − stok (Max kosong: Min − stok) untuk Kosong/Di bawah Min.",
    builder=min_max,
    columns=ITEM_COLS + (Column("warehouse_division", "Divisi Gudang", width=14), Column("qty", "Stok", "qty", width=10),
                         Column("min_stock", "Min", "qty", width=9), Column("max_stock", "Max", "qty", width=9),
                         Column("status", "Status", width=12), Column("reorder", "Saran Reorder", "qty", total=True, width=12)),
    filters=(F_DIV, F_WH, F_CAT, Filter("status", "Status", "select", MM_STATUS),
             Filter("need", "Kebutuhan", "select", (("reorder", "Hanya perlu reorder"),))),
    search_keys=ITEM_SEARCH,
))
