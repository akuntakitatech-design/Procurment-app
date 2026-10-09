"""P3 — Reporting Warehouse pada Pusat Laporan (READ-ONLY): Transfer, Pinjam & Pengembalian, Penyesuaian, Stock Opname.

Tidak menduplikasi aturan existing:
  - Visibilitas dokumen = aturan daftar existing (`server.ACCESS_FILTER_VISIBLE`: divisi header + divisi gudang header/baris).
  - Gudang/proyek/unit per BARIS dibaca dengan helper existing (`transfer_lines` / `loan_lines` / `adjustment_lines`:
    baris = sumber kebenaran, dokumen lama fallback header hanya untuk baca).
  - Qty = satuan dasar barang (sama dengan stok & ledger). Nilai = valuation ledger engine existing (net entri "Reversal X"),
    fallback snapshot baris untuk dokumen lama tanpa jejak baris; kolom nilai price=True (`view_purchase_price`).
  - Pinjam: kembali per BARIS dari ledger "Loan Return Out" (net reversal) per tanggal dokumen pengembalian <= cut-off;
    status baris memakai aturan existing (Open / Partial Returned / Completed); terlambat bila sisa > 0 dan cut-off > jatuh tempo.
  - Stock Opname: angka per baris dari `stock_opname_workflow_layer.compute_line` (aturan detail/cetak existing); nilai selisih
    hanya untuk dokumen Posted (valuation ledger "Stock Opname Adjustment"); hanya Posted yang memengaruhi stok/nilai.
Tidak ada penulisan data; transaksi, stock ledger, MWA, dan valuation tidak diubah.
"""
from __future__ import annotations

import asyncio
from datetime import date

import adjustment_lines as AL
import loan_lines as LL
import stock_opname_workflow_layer as SOW
import transfer_lines as TL
from reporting.registry import Column, Filter, ReportSpec, register
from reporting.scope import local_day

G = "warehouse"
EPS = 1e-9
F_FROM, F_TO = Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date")
F_DIV, F_WH = Filter("division_id", "Divisi", "division"), Filter("warehouse_id", "Gudang", "warehouse")
F_PROJ, F_ITEM = Filter("project_id", "Proyek", "project"), Filter("item_id", "Barang", "item")
DOC_STATUS = (("Posted", "Posted"), ("Gagal Posting", "Gagal Posting"))
LOAN_STATUS = (("Open", "Open"), ("Partial Returned", "Partial Returned"), ("Completed", "Completed"))
LATE = (("Terlambat", "Terlambat (sisa > 0, lewat jatuh tempo)"), ("Kembali Terlambat", "Kembali Terlambat"),
        ("Tepat Waktu", "Tepat Waktu"), ("Belum Jatuh Tempo", "Belum Jatuh Tempo"), ("Tanpa Jatuh Tempo", "Tanpa Jatuh Tempo"))
OPN_STATUS = ("Counting", "Review", "Waiting Approval", "Posting", "Gagal Posting", "Posted", "Cancelled")
OPN_LINE = {"uncounted": "Belum Dihitung", "match": "Cocok", "plus": "Lebih", "minus": "Kurang"}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days if a and b else None
    except ValueError:
        return None


def _in_period(day, p) -> bool:
    return (not p.get("date_from") or day >= p["date_from"]) and (not p.get("date_to") or day <= p["date_to"])


def _today():
    import stock_summary as SS
    return SS.today_iso()


# ----------------------------------------------------------------------------------------------- data dasar
async def _masters(server):
    names = ("items", "warehouses", "projects", "units", "divisions", "uoms", "item_categories")
    res = await asyncio.gather(*(getattr(server.db, n).find({}, {"_id": 0}).to_list(None) for n in names))
    m = {n: {x["id"]: x for x in rows if x.get("id")} for n, rows in zip(names, res)}
    m["uom_label"] = {k: (u.get("symbol") or u.get("code") or u.get("name")) for k, u in m["uoms"].items()}
    return m


def _item(m, iid):
    it = m["items"].get(iid) or {}
    return {"item_code": it.get("code"), "item_name": it.get("name") or iid,
            "category": (m["item_categories"].get(it.get("category_id")) or {}).get("name") or it.get("category") or "-",
            "base_unit": m["uom_label"].get(it.get("base_uom_id")) or it.get("unit") or "-"}


def _nm(m, coll, i):
    x = m[coll].get(i) or {} if i else {}
    if coll == "units":
        return x.get("plate_no") or x.get("name") or ("-" if not i else i)
    return x.get("name") or ("-" if not i else i)


async def _docs(server, user, mod, coll, p):
    """Header dalam periode (tanggal dokumen bisnis WIB, inklusif) yang terlihat menurut aturan daftar existing."""
    docs = [d for d in await getattr(server.db, coll).find({}, {"_id": 0}).to_list(None) if _in_period(local_day(d.get("date")), p)]
    fv = getattr(server, "ACCESS_FILTER_VISIBLE", None)
    return await fv(mod, docs, user) if fv and docs else docs


async def _lines(server, coll, fk, ids):
    ids = set(ids)
    if not ids:
        return {}
    rows = await getattr(server.db, coll).find({fk: {"$in": sorted(ids)}} if len(ids) <= 300 else {}, {"_id": 0}).to_list(None)
    out = {}
    for ln in rows:
        if ln.get(fk) in ids:
            out.setdefault(ln[fk], []).append(ln)
    return out


async def _ledger(server, doc_types, doc_ids):
    """Net valuation ledger per (doc_id, line_id) & (doc_id, item_id) untuk doc_type (+ "Reversal X")."""
    ids = set(doc_ids)
    if not ids:
        return {}, {}
    types = list(doc_types) + [f"Reversal {t}" for t in doc_types]
    rows = await server.db.valuation_ledger.find({"doc_type": {"$in": types}}, {"_id": 0}).to_list(None)
    rows = [r for r in rows if r.get("doc_id") in ids]
    by_id = {r.get("id"): r for r in rows if r.get("id")}
    by_line, by_item = {}, {}
    for r in rows:
        o = by_id.get(r.get("reversal_of")) if r.get("is_reversal") else None
        lid = r.get("line_id") or (o or {}).get("line_id")
        for key, bucket in (((r["doc_id"], lid), by_line), ((r["doc_id"], r.get("item_id")), by_item)):
            if key[1] is None:
                continue
            a = bucket.setdefault(key, {"qty_in": 0.0, "qty_out": 0.0, "value_in": 0.0, "value_out": 0.0, "n": 0})
            a["qty_in"] += _f(r.get("qty_in")); a["qty_out"] += _f(r.get("qty_out"))
            a["value_in"] += _f(r.get("value_in")); a["value_out"] += _f(r.get("value_out")); a["n"] += 1
    return by_line, by_item


def _led(by_line, by_item, did, ln, lines_same_item):
    """Entri ledger baris; dokumen lama tanpa line_id -> per (dokumen, barang) bila barang unik di dokumen."""
    a = by_line.get((did, ln.get("id")))
    if a is None and lines_same_item == 1:
        a = by_item.get((did, ln.get("item_id")))
    return a


def _wh_ok(p, *whs):
    return not p.get("warehouse_id") or p["warehouse_id"] in whs


def _div_ok(m, p, d, whs):
    if not p.get("division_id"):
        return True
    if d.get("division_id"):
        return d["division_id"] == p["division_id"]
    return p["division_id"] in {(m["warehouses"].get(w) or {}).get("division_id") for w in whs if w}


def _drill(page):
    return lambda r: {"label": r.get("no"), "to": f"/{page}?open={r.get('doc_id')}"} if r.get("doc_id") else None


def _register(rows, keys_sum, extra=None):
    """Register per dokumen = agregasi baris detail (satu sumber, tanpa hitung ganda)."""
    out = {}
    for r in rows:
        o = out.get(r["doc_id"])
        if o is None:
            o = out[r["doc_id"]] = {k: r.get(k) for k in ("doc_id", "no", "date", "division", "status", "created_by", "notes")}
            o.update({k: 0.0 for k in keys_sum}, line_count=0, _wf=set(), _wt=set(), _proj=set(), _items=set())
        o["line_count"] += 1
        for k in keys_sum:
            if r.get(k) is not None:
                o[k] += r[k]
        o["_wf"].add(r.get("from_wh") or r.get("warehouse")); o["_wt"].add(r.get("to_wh"))
        o["_proj"].add(r.get("project")); o["_items"].add(r.get("item_id"))
        if extra:
            extra(o, r)
    res = []
    for o in out.values():
        j = lambda s: ", ".join(sorted(x for x in s if x and x != "-")) or "-"  # noqa: E731
        o.update(from_wh=j(o.pop("_wf")), to_wh=j(o.pop("_wt")), project=j(o.pop("_proj")), item_count=len(o.pop("_items")))
        for k in keys_sum:
            o[k] = round(o[k], 6)
        res.append(o)
    res.sort(key=lambda o: (o["date"] or "", o["no"] or ""), reverse=True)
    return res


def _sort(rows):
    rows.sort(key=lambda o: (o.get("date") or "", o.get("no") or "", str(o.get("item_name") or "")), reverse=False)
    rows.sort(key=lambda o: (o.get("date") or "", o.get("no") or ""), reverse=True)
    return rows


# ----------------------------------------------------------------------------------------------- transfer
async def transfer_rows(server, user, p):
    docs, m = await asyncio.gather(_docs(server, user, "transfer", "transfers", p), _masters(server))
    lines = await _lines(server, "transfer_lines", "transfer_id", [d["id"] for d in docs])
    by_line, by_item = await _ledger(server, ("Transfer Out",), [d["id"] for d in docs])
    out = []
    for d in docs:
        ls = lines.get(d["id"], [])
        cnt = {}
        for ln in ls:
            cnt[ln.get("item_id")] = cnt.get(ln.get("item_id"), 0) + 1
        for ln in ls:
            fw, tw = TL.line_from(ln, d), TL.line_to(ln, d)
            prj, unt = TL.line_project(ln, d), TL.line_unit(ln, d)
            if not (_wh_ok(p, fw, tw) and _div_ok(m, p, d, (fw, tw)) and (not p.get("project_id") or prj == p["project_id"])
                    and (not p.get("item_id") or ln.get("item_id") == p["item_id"]) and (not p.get("status") or d.get("status") == p["status"])):
                continue
            a = _led(by_line, by_item, d["id"], ln, cnt.get(ln.get("item_id"), 0))
            val = (a["value_out"] - a["value_in"]) if a else (_f(ln.get("transfer_value")) if ln.get("transfer_value") is not None else None)
            out.append({"doc_id": d["id"], "no": d.get("no"), "date": local_day(d.get("date")), "status": d.get("status") or "-",
                        "division": _nm(m, "divisions", d.get("division_id")), "from_wh": _nm(m, "warehouses", fw),
                        "to_wh": _nm(m, "warehouses", tw), "project": _nm(m, "projects", prj), "unit": _nm(m, "units", unt),
                        "item_id": ln.get("item_id"), **_item(m, ln.get("item_id")), "qty": _f(ln.get("qty")),
                        "value": round(val, 2) if val is not None else None, "notes": ln.get("notes") or d.get("notes") or "",
                        "created_by": d.get("created_by") or "-"})
    return _sort(out)


async def transfer_register(server, user, p):
    return _register(await transfer_rows(server, user, p), ("qty", "value"))


# ----------------------------------------------------------------------------------------------- pinjam & pengembalian
async def _loan_data(server, user, p):
    cut = p.get("date_to") or _today()
    docs, m = await asyncio.gather(_docs(server, user, "loan", "loans", p), _masters(server))
    lines = await _lines(server, "loan_lines", "loan_id", [d["id"] for d in docs])
    rets = [r for r in await server.db.loan_returns.find({}, {"_id": 0}).to_list(None) if r.get("loan_id") in {d["id"] for d in docs}]
    ret_by_id = {r["id"]: r for r in rets}
    by_line, by_item = await _ledger(server, ("Loan Return Out",), list(ret_by_id))
    return cut, docs, m, lines, rets, ret_by_id, by_line, by_item


def _late(out_qty, due, done, cut):
    if not due:
        return "Tanpa Jatuh Tempo", None
    if out_qty > EPS:
        return ("Terlambat", _days(due, cut)) if cut > due else ("Belum Jatuh Tempo", None)
    if not done:
        return "Kembali Penuh (tanggal tidak tercatat)", None  # dokumen lama tanpa jejak ledger pengembalian
    return ("Kembali Terlambat", _days(due, done)) if done > due else ("Tepat Waktu", None)


def _line_returns(ln, loan_rets, ret_by_id, by_line, by_item, cut, cnt):
    """Pengembalian per baris (tanggal dokumen pengembalian <= cut-off), net reversal; urut tanggal."""
    ev = []
    for rid in loan_rets:
        a = _led(by_line, by_item, rid, ln, cnt)
        if a is None:
            continue
        q = a["qty_out"] - a["qty_in"]
        if abs(q) > EPS:
            r = ret_by_id[rid]
            ev.append((local_day(r.get("date")), r.get("no") or "", q, a["value_out"] - a["value_in"]))
    ev.sort()
    return [e for e in ev if e[0] <= cut], bool(ev)


async def loan_rows(server, user, p):
    cut, docs, m, lines, rets, ret_by_id, by_line, by_item = await _loan_data(server, user, p)
    rets_of = {}
    for r in rets:
        rets_of.setdefault(r["loan_id"], []).append(r["id"])
    out = []
    for d in docs:
        ls = lines.get(d["id"], [])
        cnt = {}
        for ln in ls:
            cnt[ln.get("item_id")] = cnt.get(ln.get("item_id"), 0) + 1
        for ln in ls:
            fw, tw = LL.line_from(ln, d), LL.line_to(ln, d)
            prj, unt = LL.line_project(ln, d), LL.line_unit(ln, d)
            if not (_wh_ok(p, fw, tw) and _div_ok(m, p, d, (fw, tw)) and (not p.get("project_id") or prj == p["project_id"])
                    and (not p.get("item_id") or ln.get("item_id") == p["item_id"])):
                continue
            qty = _f(ln.get("qty"))
            ev, traced = _line_returns(ln, rets_of.get(d["id"], []), ret_by_id, by_line, by_item, cut, cnt.get(ln.get("item_id"), 0))
            # dokumen lama tanpa jejak ledger pengembalian: akumulasi baris existing (`returned`)
            returned = sum(e[2] for e in ev) if traced or not _f(ln.get("returned")) else _f(ln.get("returned"))
            returned = min(max(returned, 0.0), qty) if qty > 0 else max(returned, 0.0)
            outstanding = max(0.0, qty - returned)
            done, acc = None, 0.0
            for e in ev:
                acc += e[2]
                if acc >= qty - EPS and done is None:
                    done = e[0]
            if outstanding > EPS:
                done = None
            day, due = local_day(d.get("date")), local_day(d.get("due_date")) if d.get("due_date") else ""
            status = "Completed" if outstanding <= EPS and qty > 0 else ("Partial Returned" if returned > EPS else "Open")
            late, late_days = _late(outstanding, due, done, cut)
            if p.get("status") and status != p["status"]:
                continue
            if p.get("late") and late != p["late"]:
                continue
            uc = _f(ln.get("cost_snapshot"))
            loan_value = _f(ln.get("loan_value")) if ln.get("loan_value") is not None else qty * uc
            out.append({"doc_id": d["id"], "no": d.get("no"), "date": day, "due_date": due or None, "status": status,
                        "division": _nm(m, "divisions", d.get("division_id")), "requester": d.get("requester") or "-",
                        "from_wh": _nm(m, "warehouses", fw), "to_wh": _nm(m, "warehouses", tw), "project": _nm(m, "projects", prj),
                        "unit": _nm(m, "units", unt), "item_id": ln.get("item_id"), **_item(m, ln.get("item_id")),
                        "qty": qty, "returned": round(returned, 6), "outstanding": round(outstanding, 6),
                        "pct": round(returned / qty * 100, 2) if qty > 0 else 0.0,
                        "age": _days(day, done or cut) if (done or outstanding > EPS) else None,
                        "full_return_date": done, "late": late, "late_days": late_days,
                        "return_refs": ", ".join(dict.fromkeys(e[1] for e in ev if e[1])) or "-",
                        "loan_value": round(loan_value, 2), "outstanding_value": round(outstanding * uc, 2),
                        "notes": ln.get("notes") or d.get("notes") or "", "created_by": d.get("created_by") or "-"})
    return _sort(out)


def _loan_extra(o, r):
    o.setdefault("due_date", r.get("due_date")); o.setdefault("requester", r.get("requester"))
    o.setdefault("_st", []).append(r["status"]); o.setdefault("_late", []).append((r.get("late_days") or 0, r["late"]))
    o.setdefault("_refs", set()).update(x for x in (r.get("return_refs") or "").split(", ") if x and x != "-")


async def loan_register(server, user, p):
    rows = _register(await loan_rows(server, user, p), ("qty", "returned", "outstanding", "loan_value", "outstanding_value"), _loan_extra)
    for o in rows:
        st = o.pop("_st")
        o["status"] = "Completed" if all(s == "Completed" for s in st) else ("Partial Returned" if any(s != "Open" for s in st) else "Open")
        lt = o.pop("_late")
        o["late"] = next((x for x in ("Terlambat", "Kembali Terlambat", "Belum Jatuh Tempo", "Tepat Waktu", "Tanpa Jatuh Tempo") if x in {v for _, v in lt}), "-")
        o["late_days"] = max((d for d, v in lt if v == o["late"]), default=0) or None
        o["return_refs"] = ", ".join(sorted(o.pop("_refs"))) or "-"
        o["pct"] = round(o["returned"] / o["qty"] * 100, 2) if o["qty"] > 0 else 0.0
    return rows


async def loan_return_rows(server, user, p):
    """Register pengembalian: periode = tanggal dokumen pengembalian (WIB); pinjaman induk harus terlihat."""
    docs, m = await asyncio.gather(_docs(server, user, "loan", "loans", {}), _masters(server))
    loans = {d["id"]: d for d in docs}
    rets = [r for r in await server.db.loan_returns.find({}, {"_id": 0}).to_list(None)
            if r.get("loan_id") in loans and _in_period(local_day(r.get("date")), p)]
    lines = await _lines(server, "loan_lines", "loan_id", {r["loan_id"] for r in rets})
    by_line, by_item = await _ledger(server, ("Loan Return Out",), [r["id"] for r in rets])
    out = []
    for r in rets:
        d = loans[r["loan_id"]]
        ls = lines.get(d["id"], [])
        cnt = {}
        for ln in ls:
            cnt[ln.get("item_id")] = cnt.get(ln.get("item_id"), 0) + 1
        for ln in ls:
            a = _led(by_line, by_item, r["id"], ln, cnt.get(ln.get("item_id"), 0))
            if a is None:
                continue
            q = a["qty_out"] - a["qty_in"]
            if abs(q) <= EPS:
                continue  # pengembalian dibatalkan/diedit (net reversal 0)
            rw_out, rw_in = LL.return_warehouses(ln, d)
            prj, unt = LL.line_project(ln, d), LL.line_unit(ln, d)
            if not (_wh_ok(p, rw_out, rw_in) and _div_ok(m, p, d, (rw_out, rw_in)) and (not p.get("project_id") or prj == p["project_id"])
                    and (not p.get("item_id") or ln.get("item_id") == p["item_id"])):
                continue
            out.append({"doc_id": d["id"], "return_no": r.get("no"), "return_date": local_day(r.get("date")), "no": d.get("no"),
                        "date": local_day(d.get("date")), "due_date": local_day(d.get("due_date")) if d.get("due_date") else None,
                        "division": _nm(m, "divisions", d.get("division_id")), "from_wh": _nm(m, "warehouses", rw_out),
                        "to_wh": _nm(m, "warehouses", rw_in), "project": _nm(m, "projects", prj), "unit": _nm(m, "units", unt),
                        **_item(m, ln.get("item_id")), "qty": round(q, 6), "value": round(a["value_out"] - a["value_in"], 2),
                        "notes": r.get("notes") or "", "created_by": r.get("created_by") or "-"})
    out.sort(key=lambda o: (o["return_date"] or "", o["return_no"] or ""), reverse=True)
    return out


# ----------------------------------------------------------------------------------------------- penyesuaian
async def adjustment_rows(server, user, p):
    docs, m = await asyncio.gather(_docs(server, user, "adjustment", "adjustments", p), _masters(server))
    lines = await _lines(server, "adjustment_lines", "adjustment_id", [d["id"] for d in docs])
    by_line, by_item = await _ledger(server, ("Stock Adjustment",), [d["id"] for d in docs])
    out = []
    for d in docs:
        ls = lines.get(d["id"], [])
        cnt = {}
        for ln in ls:
            cnt[ln.get("item_id")] = cnt.get(ln.get("item_id"), 0) + 1
        for ln in ls:
            wh, prj, unt = AL.line_warehouse(ln, d), AL.line_project(ln, d), AL.line_unit(ln, d)
            delta = _f(ln.get("adjustment"))
            if not (_wh_ok(p, wh) and _div_ok(m, p, d, (wh,)) and (not p.get("project_id") or prj == p["project_id"])
                    and (not p.get("item_id") or ln.get("item_id") == p["item_id"]) and (not p.get("status") or d.get("status") == p["status"])
                    and (not p.get("direction") or (p["direction"] == "plus") == (delta > 0))):
                continue
            a = _led(by_line, by_item, d["id"], ln, cnt.get(ln.get("item_id"), 0))
            out.append({"doc_id": d["id"], "no": d.get("no"), "date": local_day(d.get("date")), "status": d.get("status") or "-",
                        "adj_type": d.get("adj_type") or "-", "division": _nm(m, "divisions", d.get("division_id")),
                        "warehouse": _nm(m, "warehouses", wh), "project": _nm(m, "projects", prj), "unit": _nm(m, "units", unt),
                        "item_id": ln.get("item_id"), **_item(m, ln.get("item_id")), "before": _f(ln.get("before")),
                        "plus": delta if delta > 0 else 0.0, "minus": -delta if delta < 0 else 0.0, "adjustment": delta,
                        "after": _f(ln.get("after")), "reason": ln.get("reason") or d.get("reason") or "-",
                        "unit_cost": _f(ln.get("approved_unit_cost")) if ln.get("approved_unit_cost") is not None else None,
                        "value": round(a["value_in"] - a["value_out"], 2) if a else None,
                        "notes": d.get("notes") or "", "created_by": d.get("created_by") or "-"})
    return _sort(out)


def _adj_extra(o, r):
    o.setdefault("adj_type", r.get("adj_type")); o["warehouse"] = None
    o.setdefault("_reasons", set()).add(r.get("reason"))


async def adjustment_register(server, user, p):
    rows = _register(await adjustment_rows(server, user, p), ("plus", "minus", "adjustment", "value"), _adj_extra)
    for o in rows:
        o["warehouse"] = o.pop("from_wh")
        o["reason"] = ", ".join(sorted(x for x in o.pop("_reasons") if x and x != "-")) or "-"
        o.pop("to_wh", None)
    return rows


# ----------------------------------------------------------------------------------------------- stock opname
async def opname_rows(server, user, p):
    docs, m = await asyncio.gather(_docs(server, user, "opname", "opname", p), _masters(server))
    docs = [d for d in docs if _wh_ok(p, d.get("warehouse_id")) and _div_ok(m, p, d, (d.get("warehouse_id"),))
            and (not p.get("status") or d.get("status") == p["status"])]
    lines = await _lines(server, "opname_lines", "opname_id", [d["id"] for d in docs])
    posted = [d["id"] for d in docs if d.get("status") == "Posted"]
    by_line, by_item = await _ledger(server, ("Stock Opname Adjustment",), posted)
    whs = {d.get("warehouse_id") for d in docs}
    iws = {(r.get("item_id"), r.get("warehouse_id")): r for r in await server.db.item_warehouse.find({}, {"_id": 0}).to_list(None)
           if r.get("warehouse_id") in whs} if docs else {}
    out = []
    for d in docs:
        ls = lines.get(d["id"], [])
        cnt = {}
        for ln in ls:
            cnt[ln.get("item_id")] = cnt.get(ln.get("item_id"), 0) + 1
        is_posted = d.get("status") == "Posted"
        for ln in ls:
            if p.get("item_id") and ln.get("item_id") != p["item_id"]:
                continue
            c = SOW.compute_line(d, ln, iws.get((ln.get("item_id"), d.get("warehouse_id"))))
            st = OPN_LINE.get(c["status"], c["status"])
            if p.get("line_status") and st != p["line_status"]:
                continue
            val = None
            if is_posted:
                a = _led(by_line, by_item, d["id"], ln, cnt.get(ln.get("item_id"), 0))
                val = (a["value_in"] - a["value_out"]) if a else c.get("value")
            var = c["variance"]
            out.append({"doc_id": d["id"], "no": d.get("no"), "date": local_day(d.get("date")), "status": d.get("status") or "-",
                        "division": _nm(m, "divisions", d.get("division_id")), "warehouse": _nm(m, "warehouses", d.get("warehouse_id")),
                        "mode": d.get("mode") or "-", "item_id": ln.get("item_id"), **_item(m, ln.get("item_id")),
                        "system_qty": round(_f(c["system_qty"]), 6), "counted": c["counted"],
                        "variance": round(var, 6) if var is not None else None,
                        "plus_qty": var if var is not None and var > EPS else 0.0, "minus_qty": -var if var is not None and var < -EPS else 0.0,
                        "line_status": st, "reason": ln.get("reason") or "-",
                        "value": round(val, 2) if val is not None else None,
                        "plus_value": round(val, 2) if val is not None and val > 0 else (0.0 if is_posted else None),
                        "minus_value": round(-val, 2) if val is not None and val < 0 else (0.0 if is_posted else None),
                        "approved_by": d.get("approved_by_name") or d.get("approved_by") or "-",
                        "approved_at": local_day(d.get("approved_at")) if d.get("approved_at") else None,
                        "created_by": d.get("created_by_name") or d.get("created_by") or "-", "notes": d.get("notes") or ""})
    return _sort(out)


def _opn_extra(o, r):
    for k in ("warehouse", "mode", "approved_by", "approved_at"):
        o[k] = r.get(k)
    o["counted_lines"] = o.get("counted_lines", 0) + (1 if r["counted"] is not None else 0)
    for k, v in (("match", "Cocok"), ("plus_lines", "Lebih"), ("minus_lines", "Kurang")):
        o[k] = o.get(k, 0) + (1 if r["line_status"] == v else 0)


async def opname_register(server, user, p):
    rows = _register(await opname_rows(server, user, p), ("system_qty", "counted", "variance", "plus_qty", "minus_qty",
                                                         "value", "plus_value", "minus_value"), _opn_extra)
    for o in rows:
        o.pop("from_wh", None); o.pop("to_wh", None); o.pop("project", None)
        if o.get("status") != "Posted":
            o["value"] = o["plus_value"] = o["minus_value"] = None
    return rows


# ----------------------------------------------------------------------------------------------- registrasi
C_NO, C_DATE = Column("no", "No. Dokumen", width=18), Column("date", "Tanggal", "date", width=11)
C_ST, C_DIV = Column("status", "Status", width=13), Column("division", "Divisi", width=14)
C_PROJ, C_UNIT = Column("project", "Proyek", width=16), Column("unit", "Unit/Aset", width=13)
C_IC, C_IN = Column("item_code", "Kode Barang", width=12), Column("item_name", "Nama Barang", width=22)
C_SAT, C_LINES = Column("base_unit", "Satuan", width=8), Column("line_count", "Jumlah Baris", "int", total=True, width=9)
C_BY = Column("created_by", "Dibuat Oleh", width=16)
ITEM_SEARCH = ("no", "item_code", "item_name", "division", "project", "unit", "notes", "created_by")
WH_BASIS = "Periode = tanggal dokumen bisnis WIB, inklusif. Qty = satuan dasar barang. Cakupan = aturan daftar dokumen existing."
VAL_BASIS = " Nilai = valuation ledger (net pembatalan/reversal), hanya untuk izin harga."
F_DOC_ST = Filter("status", "Status", "select", DOC_STATUS)

SPECS = [
    ReportSpec(key="transfer-register", group=G, title="Transfer Antar Gudang — Register",
               description="Register dokumen transfer: gudang asal & tujuan, proyek, jumlah baris, total qty, nilai, dan status.",
               date_basis=WH_BASIS + VAL_BASIS, builder=transfer_register,
               columns=(C_NO, C_DATE, C_DIV, Column("from_wh", "Gudang Asal", width=18), Column("to_wh", "Gudang Tujuan", width=18),
                        C_PROJ, C_LINES, Column("item_count", "Jumlah Barang", "int", width=9),
                        Column("qty", "Total Qty", "qty", total=True, width=11),
                        Column("value", "Nilai Transfer", "money", price=True, total=True, width=15), C_ST, C_BY),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM, F_DOC_ST),
               search_keys=("no", "division", "from_wh", "to_wh", "project", "created_by", "notes"), drill=_drill("transfer")),
    ReportSpec(key="transfer-detail", group=G, title="Transfer Antar Gudang — Detail Barang",
               description="Detail per barang: gudang asal, gudang tujuan, proyek, unit/aset, qty, satuan, tanggal, status, nomor dokumen.",
               date_basis=WH_BASIS + VAL_BASIS, builder=transfer_rows,
               columns=(C_NO, C_DATE, C_DIV, Column("from_wh", "Gudang Asal", width=16), Column("to_wh", "Gudang Tujuan", width=16),
                        C_PROJ, C_UNIT, C_IC, C_IN, C_SAT, Column("qty", "Qty", "qty", total=True, width=10),
                        Column("value", "Nilai Transfer", "money", price=True, total=True, width=14), C_ST),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM, F_DOC_ST),
               search_keys=ITEM_SEARCH + ("from_wh", "to_wh"), drill=_drill("transfer")),
    ReportSpec(key="loan-register", group=G, title="Pinjam Barang — Register",
               description="Register pinjaman: qty dipinjam, dikembalikan, outstanding (per baris), jatuh tempo, keterlambatan, dan nilai sisa.",
               date_basis="Periode = tanggal pinjam bisnis WIB, inklusif. Cut-off = Tanggal Akhir (kosong = hari ini): pengembalian "
                          "dihitung per baris s/d cut-off. Terlambat = sisa > 0 dan cut-off melewati jatuh tempo." + VAL_BASIS,
               builder=loan_register,
               columns=(C_NO, C_DATE, Column("due_date", "Jatuh Tempo", "date", width=11), C_DIV, Column("requester", "Peminjam", width=14),
                        Column("from_wh", "Gudang Pemberi", width=16), Column("to_wh", "Gudang Peminjam", width=16), C_PROJ, C_LINES,
                        Column("qty", "Qty Dipinjam", "qty", total=True, width=10), Column("returned", "Qty Kembali", "qty", total=True, width=10),
                        Column("outstanding", "Qty Outstanding", "qty", total=True, width=11), Column("pct", "% Kembali", "qty", width=8),
                        Column("late", "Keterlambatan", width=14), Column("late_days", "Hari Terlambat", "int", width=9),
                        Column("return_refs", "No. Pengembalian", width=18),
                        Column("loan_value", "Nilai Pinjam", "money", price=True, total=True, width=14),
                        Column("outstanding_value", "Nilai Sisa", "money", price=True, total=True, width=14), C_ST),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM, Filter("status", "Status", "select", LOAN_STATUS),
                        Filter("late", "Keterlambatan", "select", LATE)),
               search_keys=("no", "division", "requester", "from_wh", "to_wh", "project", "return_refs", "created_by", "notes"),
               drill=_drill("loan")),
    ReportSpec(key="loan-detail", group=G, title="Pinjam Barang — Outstanding per Baris",
               description="Per baris pinjaman: qty dipinjam, dikembalikan, outstanding, umur pinjaman, keterlambatan, dan nilai sisa.",
               date_basis="Periode = tanggal pinjam bisnis WIB, inklusif. Cut-off = Tanggal Akhir (kosong = hari ini). Umur = tanggal pinjam "
                          "s/d pengembalian penuh, atau s/d cut-off bila belum kembali. Status baris = aturan existing." + VAL_BASIS,
               builder=loan_rows,
               columns=(C_NO, C_DATE, Column("due_date", "Jatuh Tempo", "date", width=11), C_DIV,
                        Column("from_wh", "Gudang Pemberi", width=15), Column("to_wh", "Gudang Peminjam", width=15), C_PROJ, C_UNIT,
                        C_IC, C_IN, C_SAT, Column("qty", "Qty Dipinjam", "qty", total=True, width=10),
                        Column("returned", "Qty Kembali", "qty", total=True, width=10),
                        Column("outstanding", "Qty Outstanding", "qty", total=True, width=11), Column("pct", "% Kembali", "qty", width=8),
                        Column("age", "Umur (Hari)", "int", width=8), Column("full_return_date", "Tgl Kembali Penuh", "date", width=11),
                        Column("late", "Keterlambatan", width=14), Column("late_days", "Hari Terlambat", "int", width=9),
                        Column("return_refs", "No. Pengembalian", width=16),
                        Column("outstanding_value", "Nilai Sisa", "money", price=True, total=True, width=13), C_ST),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM, Filter("status", "Status Baris", "select", LOAN_STATUS),
                        Filter("late", "Keterlambatan", "select", LATE)),
               search_keys=ITEM_SEARCH + ("from_wh", "to_wh", "return_refs", "requester"), drill=_drill("loan")),
    ReportSpec(key="loan-return-register", group=G, title="Pengembalian Pinjaman — Register",
               description="Register pengembalian per barang: no. & tanggal pengembalian, pinjaman induk, arah gudang, qty, dan nilai.",
               date_basis="Periode = tanggal dokumen pengembalian bisnis WIB, inklusif. Pengembalian yang dibatalkan/diedit dihitung net "
                          "(reversal). Nilai = harga pokok saat dipinjam (snapshot existing)." + VAL_BASIS,
               builder=loan_return_rows,
               columns=(Column("return_no", "No. Pengembalian", width=18), Column("return_date", "Tgl Pengembalian", "date", width=11),
                        Column("no", "No. Pinjaman", width=18), Column("date", "Tgl Pinjam", "date", width=11),
                        Column("due_date", "Jatuh Tempo", "date", width=11), C_DIV,
                        Column("from_wh", "Dari Gudang (Peminjam)", width=16), Column("to_wh", "Ke Gudang (Pemberi)", width=16),
                        C_PROJ, C_UNIT, C_IC, C_IN, C_SAT, Column("qty", "Qty Kembali", "qty", total=True, width=10),
                        Column("value", "Nilai Pengembalian", "money", price=True, total=True, width=14), C_BY),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM),
               search_keys=ITEM_SEARCH + ("return_no", "from_wh", "to_wh"), drill=_drill("loan")),
    ReportSpec(key="adjustment-register", group=G, title="Penyesuaian Stok — Register",
               description="Register dokumen penyesuaian: jenis, gudang, alasan, total qty (+/−), nilai penyesuaian, dan status.",
               date_basis=WH_BASIS + VAL_BASIS, builder=adjustment_register,
               columns=(C_NO, C_DATE, Column("adj_type", "Jenis", width=11), C_DIV, Column("warehouse", "Gudang", width=18), C_PROJ,
                        C_LINES, Column("plus", "Qty (+)", "qty", total=True, width=10), Column("minus", "Qty (−)", "qty", total=True, width=10),
                        Column("adjustment", "Qty Net", "qty", total=True, width=10), Column("reason", "Alasan", width=20),
                        Column("value", "Nilai Penyesuaian", "money", price=True, total=True, width=15), C_ST, C_BY),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM, F_DOC_ST,
                        Filter("direction", "Arah", "select", (("plus", "Penambahan (+)"), ("minus", "Pengurangan (−)")))),
               search_keys=("no", "adj_type", "division", "warehouse", "project", "reason", "created_by", "notes"), drill=_drill("adjustment")),
    ReportSpec(key="adjustment-detail", group=G, title="Penyesuaian Stok — Detail Barang & Gudang",
               description="Per barang & gudang: stok sebelum, penyesuaian (+/−), stok sesudah, alasan, proyek, unit/aset, dan nilai.",
               date_basis=WH_BASIS + " Stok sebelum/sesudah = snapshot baris saat posting." + VAL_BASIS, builder=adjustment_rows,
               columns=(C_NO, C_DATE, Column("adj_type", "Jenis", width=10), C_DIV, Column("warehouse", "Gudang", width=16), C_PROJ, C_UNIT,
                        C_IC, C_IN, C_SAT, Column("before", "Stok Sebelum", "qty", width=10), Column("plus", "Qty (+)", "qty", total=True, width=9),
                        Column("minus", "Qty (−)", "qty", total=True, width=9), Column("after", "Stok Sesudah", "qty", width=10),
                        Column("reason", "Alasan", width=18), Column("unit_cost", "Harga Satuan", "money", price=True, width=13),
                        Column("value", "Nilai Penyesuaian", "money", price=True, total=True, width=14), C_ST),
               filters=(F_FROM, F_TO, F_DIV, F_WH, F_PROJ, F_ITEM, F_DOC_ST,
                        Filter("direction", "Arah", "select", (("plus", "Penambahan (+)"), ("minus", "Pengurangan (−)")))),
               search_keys=ITEM_SEARCH + ("warehouse", "reason", "adj_type"), drill=_drill("adjustment")),
    ReportSpec(key="opname-register", group=G, title="Stock Opname — Register",
               description="Register stock opname per gudang & status: rekap stok sistem, hitung fisik, selisih qty/nilai, dan approval.",
               date_basis="Periode = tanggal dokumen opname bisnis WIB, inklusif. Angka per baris = aturan detail opname existing. Hanya "
                          "dokumen Posted yang memengaruhi stok & nilai; nilai selisih hanya untuk Posted (valuation ledger), izin harga.",
               builder=opname_register,
               columns=(C_NO, C_DATE, Column("warehouse", "Gudang", width=16), C_DIV, Column("mode", "Mode", width=8),
                        Column("item_count", "Jumlah Barang", "int", total=True, width=9), Column("counted_lines", "Sudah Dihitung", "int", total=True, width=9),
                        Column("match", "Cocok", "int", total=True, width=7), Column("plus_lines", "Lebih", "int", total=True, width=7),
                        Column("minus_lines", "Kurang", "int", total=True, width=7),
                        Column("system_qty", "Qty Sistem", "qty", total=True, width=11), Column("counted", "Qty Fisik", "qty", total=True, width=11),
                        Column("plus_qty", "Selisih (+)", "qty", total=True, width=10), Column("minus_qty", "Selisih (−)", "qty", total=True, width=10),
                        Column("variance", "Selisih Net", "qty", total=True, width=10),
                        Column("plus_value", "Nilai Lebih", "money", price=True, total=True, width=13),
                        Column("minus_value", "Nilai Kurang", "money", price=True, total=True, width=13),
                        Column("value", "Nilai Selisih Net", "money", price=True, total=True, width=14),
                        C_ST, Column("approved_by", "Disetujui Oleh", width=14), Column("approved_at", "Tgl Disetujui", "date", width=11), C_BY),
               filters=(F_FROM, F_TO, F_WH, F_DIV, Filter("status", "Status", "select", tuple((s, s) for s in OPN_STATUS)), F_ITEM),
               search_keys=("no", "warehouse", "division", "status", "approved_by", "created_by", "notes"), drill=_drill("opname")),
    ReportSpec(key="opname-detail", group=G, title="Stock Opname — Detail Selisih Barang",
               description="Per barang: stok sistem, hitung fisik, selisih qty, alasan, nilai selisih (Posted), status, dan approval.",
               date_basis="Periode = tanggal dokumen opname bisnis WIB, inklusif. Stok sistem = aturan existing (snapshot/freeze, saat hitung, "
                          "atau saat posting). Nilai selisih hanya dokumen Posted (valuation ledger, net koreksi), izin harga.",
               builder=opname_rows,
               columns=(C_NO, C_DATE, Column("warehouse", "Gudang", width=15), C_DIV, C_IC, C_IN, C_SAT,
                        Column("system_qty", "Stok Sistem", "qty", total=True, width=10), Column("counted", "Hitung Fisik", "qty", total=True, width=10),
                        Column("variance", "Selisih Qty", "qty", total=True, width=10), Column("line_status", "Hasil", width=11),
                        Column("reason", "Alasan", width=18), Column("value", "Nilai Selisih", "money", price=True, total=True, width=14),
                        C_ST, Column("approved_by", "Disetujui Oleh", width=14)),
               filters=(F_FROM, F_TO, F_WH, F_DIV, Filter("status", "Status", "select", tuple((s, s) for s in OPN_STATUS)), F_ITEM,
                        Filter("line_status", "Hasil Hitung", "select", tuple((v, v) for v in OPN_LINE.values()))),
               search_keys=("no", "warehouse", "item_code", "item_name", "reason", "status", "approved_by"), drill=_drill("opname")),
]
for _s in SPECS:
    register(_s)
