"""P4 — Reporting SPK & Kontrak Harga Vendor pada Pusat Laporan (READ-ONLY).

Tidak ada engine kedua — seluruh angka memakai sumber yang SAMA dengan Dashboard:
  A. Realisasi Anggaran SPK = reporting.spk (rows_at / positions / drill): Budget = procurement_budget per cut-off
     (addendum effective sesudah cut-off dikeluarkan), Commitment = spk_commitment_ledger (COMMIT − RELEASE + ADJUST),
     Realisasi = porsi SPK barang diterima lewat DO valid (bagian dari Commitment), Open = Commitment − Realisasi,
     Sisa Budget = Budget − Commitment. Nilai Kontrak SPK (spk_value) ditampilkan TERPISAH dan tidak ikut perhitungan.
     Detail: per (SPK, baris PO) dan per (SPK, baris DO) — tanpa hitung ganda PO multi-SPK / DO parsial / reversal.
  B. Daftar Kontrak Harga Vendor = status posisi cut-off reporting.price_control.contract_rows (Aktif / Akan Berakhir
     ⊂ Aktif / Expired) + Draft / Cancelled / Belum Berlaku; harga efektif cut-off lewat resolver existing +
     reporting.contract_history (versi harga historis read-only).
  C. Kepatuhan Harga PO vs Kontrak = reporting.price_control.price_lines atas PO periode yang sama dengan Dashboard
     (reporting.service._po_period_rows: Approved final / Partially / Fully Received). Harga PO = DPP/unit engine PO.
Izin: A wajib spk:view (nominal SPK = paritas Dashboard), harga satuan PO di detail + view_purchase_price;
B wajib vendor_contract:view, harga + view_purchase_price; C wajib po.view, harga/selisih = vendor_contract:view AND
view_purchase_price (kolom dibuang server-side dari JSON, total, Excel, PDF).
"""
from __future__ import annotations

from datetime import date

from reporting import contract_history as CH
from reporting import price_control as PC
from reporting import scope as S
from reporting import spk as SPK
from reporting.registry import Column, Filter, ReportSpec, register

G = "spk"
VC = ("vendor_contract:view",)
SPK_STATUS = {"draft": "Draft", "active": "Active", "closed": "Closed", "cancelled": "Cancelled"}
F_CUT = Filter("date_to", "Tanggal Posisi (Cut-off)", "date")
F_DIV, F_PROJ = Filter("division_id", "Divisi", "division"), Filter("project_id", "Proyek", "project")
F_SUP, F_ITEM = Filter("supplier_id", "Supplier", "supplier"), Filter("item_id", "Barang", "item")
F_SPK_STATUS = Filter("status", "Status SPK", "select", (
    ("active_closed", "Active + Closed"), ("all", "Semua Status"), ("draft", "Draft"), ("active", "Active"),
    ("closed", "Closed"), ("cancelled", "Cancelled")), default="active_closed")
F_SPK_ID = Filter("spk_id", "SPK", "text", hidden=True)  # halaman detail SPK: posisi satu SPK dari perhitungan yang sama
F_KONDISI = Filter("kondisi", "Posisi / Kondisi", "select", (
    ("active", "Aktif pada cut-off"), ("expiring", "Akan Berakhir ≤ 30 Hari"), ("over", "Over Budget"),
    ("critical", "Kritis (> 90%)"), ("attention", "Perlu Perhatian"), ("ended", "Masa Berlaku Berakhir")))
SPK_NOTE = ("Posisi per Tanggal Posisi (WIB; kosong = hari ini) — sama dengan Dashboard SPK & Budget Control. Commitment, Sisa "
            "Budget dan % Pemakaian dihitung dari Anggaran Procurement; Nilai Kontrak SPK hanya informasi nilai pekerjaan. "
            "Sisa Budget = Budget − Commitment (Realisasi DO bagian dari Commitment). SPK yang mulai setelah Tanggal Posisi tidak "
            "ditampilkan.")


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def _fmt_day(v):
    v = str(v or "")[:10]
    return f"{v[8:10]}-{v[5:7]}-{v[0:4]}" if len(v) == 10 else "-"


def _rp(v):
    return f"{int(round(float(v or 0))):,}".replace(",", ".")


# ----------------------------------------------------------------------------------------------- A. SPK
async def _spk_base(server, user, p):
    cut = S.asof(S.resolve_filters(server, user, None, p.get("date_to") or S.today().isoformat()))
    f = S.Filters(None, cut, p.get("division_id") or None, p.get("project_id") or None, None, S.today().isoformat())
    data = await SPK.load(server)  # active + closed (sumber Dashboard)
    st = p.get("status") or "active_closed"
    if st in ("all", "draft", "cancelled"):
        extra = await server.db.spk.find({"status": {"$in": ["draft", "cancelled"]}}, {"_id": 0}).to_list(None)
        data = {**data, "spk": data["spk"] + extra}
    rows = SPK.rows_at(data, f, cut, user, server)
    if p.get("spk_id"):
        rows = [r for r in rows if r["id"] == p["spk_id"]]
    if st not in ("all", "active_closed"):
        rows = [r for r in rows if r["status"] == st]
    k = p.get("kondisi")
    if k in SPK.DRILL_KINDS:
        rows = SPK.drill(rows, k)  # predikat = KPI / drill Dashboard (paritas)
    elif k == "ended":
        rows = [r for r in rows if not r["active"] and r["end_date"] and r["end_date"] < cut]
    else:
        rows = sorted(rows, key=lambda r: str(r.get("spk_number") or ""))
    return data, f, cut, rows


async def spk_budget(server, user, p):
    data, _f, cut, rows = await _spk_base(server, user, p)
    full = {s["id"]: s for s in data["spk"]}
    adds = {}
    for a in data["adds"]:
        adds.setdefault(a.get("spk_id"), []).append(a)
    out = []
    for r in rows:
        s, ad = full.get(r["id"]) or {}, adds.get(r["id"], [])
        upto = [a for a in ad if SPK._add_day(a) <= cut]
        v_all, v_cut = sum(int(a.get("spk_value_change") or 0) for a in ad), sum(int(a.get("spk_value_change") or 0) for a in upto)
        b_cut = sum(int(a.get("budget_change") or 0) for a in upto)
        v0 = int(s.get("spk_value") or 0) - v_all
        end = r["end_date"]
        validity = ("Akan Berakhir (≤ 30 hari)" if r["expiring"] else "Berlaku") if r["active"] else \
            ("Berakhir" if end and end < cut else "-")
        out.append({"id": r["id"], "no": r["spk_number"], "title": r.get("title") or s.get("customer") or "-",
                    "project": r.get("project_name") or "-", "division": r.get("division_name") or "-",
                    "status": SPK_STATUS.get(r["status"], r["status"]), "start_date": r["start_date"], "end_date": end,
                    "validity": validity, "days_left": _days(cut, end) if end else None,
                    "addendum_count": len(upto), "spk_value_initial": v0, "spk_value_add": v_cut, "spk_value_final": v0 + v_cut,
                    "budget_initial": r["budget"] - b_cut, "budget_add": b_cut, "budget_final": r["budget"],
                    "commitment": r["commitment"], "realization": r["realization"], "open_commitment": r["open_commitment"],
                    "remaining": r["remaining"], "usage_pct": r["usage_pct"], "level": r["level_label"],
                    "flags": ", ".join(r["flags"]) or "-"})
    return out


async def _po_info(server, po_ids, pl_ids):
    po_ids, pl_ids = sorted({x for x in po_ids if x}), sorted({x for x in pl_ids if x})
    heads = await server.db.po.find({"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "no": 1, "date": 1, "status": 1,
                                                             "supplier_name": 1}).to_list(None) if po_ids else []
    lines = await server.db.po_lines.find({"id": {"$in": pl_ids}}, {"_id": 0, "id": 1, "po_id": 1, "item_id": 1,
                                                                   "unit": 1}).to_list(None) if pl_ids else []
    import doc_procurement
    items = (await doc_procurement.maps())["items"]
    return {h["id"]: h for h in heads}, {x["id"]: x for x in lines}, items


async def _spk_lines(server, user, p):
    data, _f, cut, rows = await _spk_base(server, user, p)
    ids = {r["id"]: r for r in rows}
    pos = SPK.positions(data, set(ids), cut)
    led = {}
    for e in data["ledger"]:
        if e.get("spk_id") in ids and e.get("po_line_id"):
            led.setdefault((e["spk_id"], e["po_line_id"]), e)
    heads, plines, items = await _po_info(server, [e.get("po_id") for e in led.values()], [k[1] for k in pos["com"]])
    return data, cut, ids, pos, led, heads, plines, items


def _item_cols(items, iid):
    it = items.get(iid) or {}
    return {"item_id": iid, "item_code": it.get("code") or "-", "item_name": it.get("name") or iid or "-"}


async def spk_budget_po(server, user, p):
    _data, _cut, ids, pos, led, heads, plines, items = await _spk_lines(server, user, p)
    dos_of = {}
    for sid, pl, x, dd, qq in pos["events"]:
        dos_of.setdefault((sid, pl), set()).add(x.get("do_id"))
    do_no = {}
    if dos_of:
        dids = sorted({d for s in dos_of.values() for d in s if d})
        do_no = {d["id"]: d.get("no") for d in await server.db.do.find({"id": {"$in": dids}}, {"_id": 0, "id": 1, "no": 1}).to_list(None)}
    out = []
    for (sid, pl), amt in pos["com"].items():
        e, ln = led.get((sid, pl)) or {}, plines.get(pl) or {}
        po_id = ln.get("po_id") or e.get("po_id")
        h = heads.get(po_id) or {}
        aq, rq = SPK.committed_qty(pos, sid, pl), pos["recv"].get((sid, pl), 0)
        real = amt * min(rq, aq) / aq if amt > 0 and aq > 0 else 0.0
        out.append({"spk_id": sid, "spk_no": ids[sid]["spk_number"], "po_id": po_id, "no": h.get("no") or e.get("po_no") or "-",
                    "po_date": S.day(h, "date") or None, "po_status": h.get("status") or "-",
                    "supplier": h.get("supplier_name") or "-", **_item_cols(items, ln.get("item_id") or e.get("item_id")),
                    "unit": ln.get("unit") or "-", "qty_commit": aq, "qty_received": round(min(rq, aq) if aq > 0 else rq, 6),
                    "do_refs": ", ".join(sorted(do_no.get(d) or "-" for d in dos_of.get((sid, pl), ()))) or "-",
                    "commit_state": "Committed" if amt > 0 else "Dirilis (Cancel / Reject / Edit)",
                    "commitment": amt, "realization": round(real, 2), "open_commitment": round(max(amt - real, 0), 2),
                    "unit_price": round(amt / aq, 2) if aq > 0 and amt > 0 else None})
    out.sort(key=lambda r: (r["spk_no"] or "", r["po_date"] or "", r["no"] or "", r["item_code"]))
    return [r for r in out if not p.get("item_id") or r["item_id"] == p["item_id"]]


async def spk_budget_do(server, user, p):
    data, _cut, ids, pos, _led, heads, plines, items = await _spk_lines(server, user, p)
    explicit = {a.get("item_line_id") for a in data["allocs"] if a.get("source_type") == "do"}
    dids = sorted({x.get("do_id") for _s, _p, x, _d, _q in pos["events"] if x.get("do_id")})
    dos = {d["id"]: d for d in await server.db.do.find({"id": {"$in": dids}}, {"_id": 0, "id": 1, "no": 1, "status": 1}).to_list(None)} if dids else {}
    by = {}
    for ev in pos["events"]:
        by.setdefault((ev[0], ev[1]), []).append(ev)
    out = []
    for (sid, pl), evs in by.items():
        amt, aq = pos["com"].get((sid, pl), 0), SPK.committed_qty(pos, sid, pl)
        rem = aq
        ln = plines.get(pl) or {}
        h = heads.get(ln.get("po_id")) or {}
        for _s, _p, x, dd, qq in sorted(evs, key=lambda e: (e[3], str((dos.get(e[2].get("do_id")) or {}).get("no") or ""))):
            cnt = max(min(qq, rem), 0)
            rem -= cnt
            d = dos.get(x.get("do_id")) or {}
            out.append({"spk_id": sid, "spk_no": ids[sid]["spk_number"], "do_id": x.get("do_id"), "no": d.get("no") or "-",
                        "do_date": dd, "do_status": d.get("status") or "-", "po_no": h.get("no") or "-",
                        "supplier": h.get("supplier_name") or "-", **_item_cols(items, x.get("item_id") or ln.get("item_id")),
                        "qty_do": round(qq, 6), "qty_counted": round(cnt, 6),
                        "basis": "Alokasi SPK pada DO" if x.get("id") in explicit else "Proporsional porsi SPK baris PO",
                        "realization": round(amt * cnt / aq, 2) if amt > 0 and aq > 0 else 0.0})
    out.sort(key=lambda r: (r["spk_no"] or "", r["do_date"] or "", r["no"] or ""))
    return [r for r in out if not p.get("item_id") or r["item_id"] == p["item_id"]]


# ----------------------------------------------------------------------------------------------- B. Kontrak
CONTRACT_FILTER = (("active", "Aktif (termasuk Akan Berakhir)"), ("expiring", "Akan Berakhir ≤ 30 Hari"), ("expired", "Expired"),
                   ("not_started", "Belum Berlaku"), ("draft", "Draft"), ("cancelled", "Cancelled"))


def _tolerance(c, it):
    return float(it.get("tolerance_pct") or 0) if (it.get("tolerance_mode") or "").upper() == "CUSTOM" \
        else float(c.get("default_tolerance_pct") or 0)


def _changes_text(changes):
    return "; ".join(f"{_fmt_day(h.get('effective_date'))}: {_rp(h.get('previous_net_price'))} → {_rp(h.get('new_net_price'))}"
                     for h in changes) or "-"


async def contract_list(server, user, p):
    cut = S.asof(S.resolve_filters(server, user, None, p.get("date_to") or S.today().isoformat()))
    data = await PC.load(server, [])
    f = S.Filters(None, cut, None, None, p.get("supplier_id") or None, S.today().isoformat())
    pos = {r["id"]: r for r in PC.contract_rows(data["contracts"], data["items"], f, cut)}  # = KPI / drill Dashboard
    groups, hidx = PC._groups(data), CH.index(data.get("history"))
    pick = server.pick_vendor_contract_price
    sup_names = {s["id"]: s.get("name") for s in await server.db.suppliers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(None)}
    items_of = {}
    for it in data["items"]:
        items_of.setdefault(it.get("contract_id"), []).append(it)
    out = []
    for c in data["contracts"]:
        if p.get("supplier_id") and c.get("supplier_id") != p["supplier_id"]:
            continue
        st, r = c.get("status"), pos.get(c["id"])
        if st == "active" and r:
            key = "expired" if r["expired"] else ("expiring" if r["expiring"] else "active")
            label = {"expired": "Expired", "expiring": "Aktif · Akan Berakhir", "active": "Aktif"}[key]
        else:
            key = {"draft": "draft", "cancelled": "cancelled"}.get(st, "not_started")
            label = {"draft": "Draft", "cancelled": "Cancelled", "not_started": "Belum Berlaku"}[key]
        want = p.get("status")
        if want and not (want == key or (want == "active" and key == "expiring")):
            continue
        end = S.day(c, "end_date") or None
        head = {"contract_id": c["id"], "no": c.get("contract_number") or "-",
                "supplier": c.get("supplier_name") or sup_names.get(c.get("supplier_id")) or "-",
                "contract_date": S.day(c, "contract_date") or None, "start_date": S.day(c, "start_date") or None,
                "end_date": end, "status": label, "days_left": _days(cut, end) if end and key in ("active", "expiring") else None}
        its = sorted(items_of.get(c["id"], []), key=lambda i: (str(i.get("item_code") or ""), float(i.get("min_qty") or 0)))
        if p.get("item_id"):
            its = [i for i in its if i.get("item_id") == p["item_id"]]
            if not its:
                continue
        if not its:
            out.append({**head, "item_code": "-", "item_name": "(belum ada barang)", "uom": "-", "resolver": "-"})
            continue
        for it in its:
            s0, e0 = CH._period(it, c)
            res = None
            if key in ("active", "expiring"):
                res = CH.resolve(pick, c.get("supplier_id"), it.get("item_id"), it.get("uom_id"),
                                 groups.get((c.get("supplier_id"), it.get("item_id"), it.get("uom_id")), []), cut,
                                 float(it.get("min_qty") or 0), hidx)
            if key not in ("active", "expiring"):
                src = "-"
            elif not res:
                src = "Tidak berlaku pada cut-off"
            elif res.get("incomplete"):
                src = "Riwayat Harga Tidak Lengkap"
            elif res.get("item_row_id") == it.get("id"):
                src = "Baris ini" + (" (versi riwayat harga)" if res.get("price_version") == "historical" else "")
            else:
                src = f"Kontrak / tier lain: {res.get('contract_number')}"
            ch = hidx.get(it.get("id")) or []
            dt = (it.get("discount_type") or "NONE").upper()
            out.append({**head, "item_id": it.get("item_id"), "item_code": it.get("item_code") or "-", "item_name": it.get("item_name") or "-",
                        "uom": it.get("uom_name") or "-", "min_qty": float(it.get("min_qty") or 0),
                        "base_price": int(it.get("base_price") or 0),
                        "discount": {"PERCENT": f"{it.get('discount_value')}%", "AMOUNT": _rp(it.get("discount_value"))}.get(dt, "-"),
                        "net_price": int(it.get("net_price") or 0), "tolerance_pct": _tolerance(c, it),
                        "item_start": s0 if s0 != CH.FAR_PAST else None, "item_end": e0 if e0 != CH.FAR_FUTURE else None,
                        "lead_time": int(it.get("lead_time_days") or 0), "price_changes": len(ch), "changes_text": _changes_text(ch),
                        "resolver": src,
                        "price_at_cut": (res or {}).get("net_contract_price") if res and not res.get("incomplete") else None})
    out.sort(key=lambda r: (r["no"], str(r.get("item_code") or ""), r.get("min_qty") or 0))
    return out


# ----------------------------------------------------------------------------------------------- C. Kepatuhan Harga
COMPLIANCE_FILTER = (("ok", "Sesuai"), ("over", "Melebihi Tolerance"), ("no_contract", "Tanpa Kontrak"),
                     ("history_incomplete", "Riwayat Harga Tidak Lengkap"), ("exceptions", "Seluruh Pengecualian (selain Sesuai)"))


async def compliance(server, user, p):
    from reporting import service as SV
    df, dt = p.get("date_from"), p.get("date_to")
    f = S.resolve_filters(server, user, df, dt, p.get("division_id"), p.get("project_id"), p.get("supplier_id"),
                          None if (df or dt) else "all")
    perm = S.permissions(server, user)
    po_rows = await SV._po_period_rows(server, user, f, perm)  # predikat & as-of SAMA dengan Dashboard
    data = await PC.load(server, [r["id"] for r in po_rows])
    lines = PC.price_lines(po_rows, data, server.pick_vendor_contract_price)
    lines = PC.price_drill(lines, "all")  # urutan = drill Dashboard
    st = p.get("status")
    if st == "exceptions":
        lines = [r for r in lines if r["status"] != "ok"]
    elif st:
        lines = [r for r in lines if r["status"] == st]
    if p.get("item_id"):
        lines = [r for r in lines if r.get("item_id") == p["item_id"]]
    rows = await SV._item_names([dict(r) for r in lines])
    out = []
    for r in rows:
        ver = "-"
        if r["status"] in ("ok", "over"):
            ver = (f"Riwayat — berlaku mulai {_fmt_day(r.get('price_version_from'))}" if r.get("price_version") == "historical"
                   else "Saat ini")
        out.append({"po_id": r["po_id"], "no": r.get("po_no") or "-", "po_date": r.get("po_date"), "po_status": r.get("po_status") or "-",
                    "supplier": r.get("supplier_name") or "-", "item_id": r.get("item_id"), "item_code": r.get("item_code") or "-",
                    "item_name": r.get("item_name") or "-", "qty": r.get("qty"), "uom": r.get("uom") or "-",
                    "contract_no": r.get("contract_number") or "-", "price_version": ver,
                    "po_price": round(r["po_price"], 2) if r.get("po_price") is not None else None,
                    "contract_price": r.get("contract_price"), "tolerance_pct": r.get("tolerance_pct"),
                    "allowed_max": round(r["allowed_max"], 2) if r.get("allowed_max") is not None else None,
                    "diff_unit": round(r["diff_unit"], 2) if r.get("diff_unit") is not None else None,
                    "diff": round(r["diff"], 2) if r.get("diff") is not None else None, "diff_pct": r.get("diff_pct"),
                    "status": r["status_label"], "price_status_snapshot": r.get("price_status_snapshot") or "-",
                    "price_change_reason": r.get("price_change_reason") or "-",
                    "contract_changes": _changes_text(r.get("history_changes") or [])})
    return out


# ----------------------------------------------------------------------------------------------- registrasi
def _drill(page, idk):
    return lambda r: {"label": r.get("no"), "to": f"/{page}/{r.get(idk)}"} if r.get(idk) else None


M = lambda k, lb, w=15, **kw: Column(k, lb, "money", total=True, width=w, **kw)  # noqa: E731

SPECS = [
    ReportSpec(
        key="spk-budget", group=G, title="Realisasi Anggaran SPK",
        description="Rekap seluruh SPK: nilai kontrak & anggaran procurement (awal, addendum efektif, akhir), commitment PO "
                    "Approved final, realisasi DO, open commitment, sisa budget, dan % pemakaian.",
        columns=(Column("no", "No. SPK", width=16), Column("title", "Nama SPK / Pekerjaan", width=24), Column("project", "Proyek", width=18),
                 Column("division", "Divisi", width=14), Column("status", "Status", width=10), Column("start_date", "Mulai", "date", width=11),
                 Column("end_date", "Berakhir", "date", width=11), Column("validity", "Masa Berlaku", width=16),
                 Column("days_left", "Sisa Hari", "int", width=8), Column("addendum_count", "Addendum Efektif", "int", width=9),
                 M("spk_value_initial", "Nilai Kontrak SPK Awal"), M("spk_value_add", "Addendum Nilai Kontrak"),
                 M("spk_value_final", "Nilai Kontrak SPK Akhir"), M("budget_initial", "Anggaran Procurement Awal"),
                 M("budget_add", "Addendum Anggaran"), M("budget_final", "Anggaran Procurement Akhir"),
                 M("commitment", "Commitment (PO Approved)"), M("realization", "Realisasi DO"),
                 M("open_commitment", "Open Commitment"), M("remaining", "Sisa Budget"),
                 Column("usage_pct", "% Pemakaian", "qty", width=9), Column("level", "Level", width=11),
                 Column("flags", "Perlu Perhatian", width=22)),
        builder=spk_budget, filters=(F_CUT, F_DIV, F_PROJ, F_SPK_STATUS, F_KONDISI, F_SPK_ID),
        search_keys=("no", "title", "project", "division", "status"), permission="spk:view", date_basis=SPK_NOTE,
        drill=_drill("spk", "id")),
    ReportSpec(
        key="spk-budget-po", group=G, title="Realisasi Anggaran SPK — Detail Baris PO",
        description="Commitment per SPK per baris PO (porsi SPK pada PO multi-SPK), qty diterima, realisasi, dan open commitment.",
        columns=(Column("spk_no", "No. SPK", width=16), Column("no", "No. PO", width=16), Column("po_date", "Tgl PO", "date", width=11),
                 Column("po_status", "Status PO", width=13), Column("supplier", "Supplier", width=18),
                 Column("item_code", "Kode Barang", width=12), Column("item_name", "Nama Barang", width=22), Column("unit", "Satuan", width=8),
                 Column("qty_commit", "Qty SPK (Commit)", "qty", width=11), Column("qty_received", "Qty Diterima (DO)", "qty", width=11),
                 Column("do_refs", "No. DO", width=18), Column("commit_state", "Status Commitment", width=16),
                 Column("unit_price", "Harga Satuan Commit", "money", price=True, width=14),
                 M("commitment", "Commitment"), M("realization", "Realisasi DO"), M("open_commitment", "Open Commitment")),
        builder=spk_budget_po, filters=(F_CUT, F_DIV, F_PROJ, F_SPK_STATUS, F_KONDISI, F_ITEM, F_SPK_ID),
        search_keys=("spk_no", "no", "supplier", "item_code", "item_name", "do_refs"), permission="spk:view",
        date_basis=SPK_NOTE + " Satu baris = porsi satu SPK pada satu baris PO (ledger commitment); PO multi-SPK tidak dihitung ganda.",
        drill=_drill("po", "po_id")),
    ReportSpec(
        key="spk-budget-do", group=G, title="Realisasi Anggaran SPK — Detail Baris DO",
        description="Realisasi per SPK per baris DO valid s/d cut-off; qty dihitung dibatasi qty commitment (DO parsial / berulang).",
        columns=(Column("spk_no", "No. SPK", width=16), Column("no", "No. DO", width=16), Column("do_date", "Tgl DO", "date", width=11),
                 Column("do_status", "Status DO", width=13), Column("po_no", "No. PO", width=16), Column("supplier", "Supplier", width=18),
                 Column("item_code", "Kode Barang", width=12), Column("item_name", "Nama Barang", width=22),
                 Column("qty_do", "Qty DO (Porsi SPK)", "qty", width=11), Column("qty_counted", "Qty Dihitung Realisasi", "qty", width=11),
                 Column("basis", "Dasar Alokasi", width=20), M("realization", "Realisasi DO")),
        builder=spk_budget_do, filters=(F_CUT, F_DIV, F_PROJ, F_SPK_STATUS, F_KONDISI, F_ITEM, F_SPK_ID),
        search_keys=("spk_no", "no", "po_no", "supplier", "item_code", "item_name"), permission="spk:view",
        date_basis=SPK_NOTE + " Hanya DO valid (tidak batal) bertanggal ≤ Tanggal Posisi; DO batal / reversal tidak dihitung.",
        drill=_drill("do", "do_id")),
    ReportSpec(
        key="vendor-contract-list", group=G, title="Daftar Kontrak Harga Vendor",
        description="Kontrak harga vendor & barangnya: satuan, harga kontrak, tolerance, masa berlaku, status per cut-off, dan "
                    "harga efektif menurut Effective Price Resolver.",
        columns=(Column("no", "No. Kontrak", width=16), Column("supplier", "Supplier", width=20),
                 Column("contract_date", "Tgl Kontrak", "date", width=11), Column("start_date", "Mulai", "date", width=11),
                 Column("end_date", "Berakhir", "date", width=11), Column("status", "Status (Cut-off)", width=16),
                 Column("days_left", "Sisa Hari", "int", width=8), Column("item_code", "Kode Barang", width=12),
                 Column("item_name", "Nama Barang", width=22), Column("uom", "Satuan", width=8), Column("min_qty", "Min. Qty", "qty", width=8),
                 Column("base_price", "Harga Dasar", "money", price=True, width=13), Column("discount", "Diskon", price=True, width=9),
                 Column("net_price", "Harga Kontrak (Net)", "money", price=True, width=14),
                 Column("tolerance_pct", "Tolerance %", "qty", width=9), Column("item_start", "Berlaku Mulai", "date", width=11),
                 Column("item_end", "Berlaku s/d", "date", width=11), Column("lead_time", "Lead Time (hari)", "int", width=8),
                 Column("price_changes", "Perubahan Harga", "int", width=8),
                 Column("changes_text", "Riwayat Perubahan Harga (tgl efektif: lama → baru)", price=True, width=26),
                 Column("resolver", "Resolver pada Cut-off", width=20),
                 Column("price_at_cut", "Harga Efektif Cut-off", "money", price=True, width=14)),
        builder=contract_list, filters=(F_CUT, Filter("status", "Status Kontrak", "select", CONTRACT_FILTER), F_SUP, F_ITEM),
        search_keys=("no", "supplier", "item_code", "item_name", "status"), permission="vendor_contract:view",
        date_basis="Status per Tanggal Posisi (WIB; kosong = hari ini) — aturan Dashboard: Aktif = active & mulai ≤ cut-off ≤ berakhir; "
                   "Akan Berakhir = Aktif dengan sisa 0–30 hari (bagian dari Aktif); Expired = berakhir < cut-off. Harga = data kontrak "
                   "kini; Harga Efektif Cut-off = Effective Price Resolver existing (qty = Min. Qty baris) termasuk versi harga historis.",
        drill=_drill("vendor-contracts", "contract_id")),
    ReportSpec(
        key="price-compliance", group=G, title="Kepatuhan Harga PO vs Kontrak",
        description="Harga efektif PO (DPP/unit sebelum pajak) dibanding harga kontrak yang berlaku pada tanggal PO untuk vendor, "
                    "barang, dan satuan yang sama: selisih, persentase, dan status kepatuhan.",
        columns=(Column("no", "No. PO", width=16), Column("po_date", "Tgl PO", "date", width=11),
                 Column("po_status", "Status PO (Approval)", width=14), Column("supplier", "Supplier", width=18),
                 Column("item_code", "Kode Barang", width=12), Column("item_name", "Nama Barang", width=22),
                 Column("qty", "Qty", "qty", width=8), Column("uom", "Satuan", width=8), Column("contract_no", "No. Kontrak", width=16),
                 Column("price_version", "Versi Harga Kontrak", width=18),
                 Column("po_price", "Harga PO Net / Unit", "money", price=True, perms=VC, width=14),
                 Column("contract_price", "Harga Kontrak / Unit", "money", price=True, perms=VC, width=14),
                 Column("tolerance_pct", "Tolerance %", "qty", price=True, perms=VC, width=9),
                 Column("allowed_max", "Batas Maks. / Unit", "money", price=True, perms=VC, width=14),
                 Column("diff_unit", "Selisih / Unit", "money", price=True, perms=VC, width=12),
                 Column("diff", "Selisih Total", "money", price=True, perms=VC, total=True, width=14),
                 Column("diff_pct", "Selisih %", "qty", price=True, perms=VC, width=8),
                 Column("status", "Status Kepatuhan", width=16), Column("price_status_snapshot", "Status Harga saat Input PO", width=16),
                 Column("price_change_reason", "Alasan Perubahan Harga (PO)", width=20),
                 Column("contract_changes", "Riwayat Perubahan Harga Kontrak", price=True, perms=VC, width=24)),
        builder=compliance,
        filters=(Filter("date_from", "Tanggal Awal (Tgl PO)", "date"), Filter("date_to", "Tanggal Akhir (Tgl PO)", "date"), F_DIV, F_PROJ,
                 F_SUP, F_ITEM, Filter("status", "Status Kepatuhan", "select", COMPLIANCE_FILTER)),
        search_keys=("no", "supplier", "item_code", "item_name", "contract_no", "status"), permission="po.view",
        date_basis="PO bertanggal dalam periode (WIB) berstatus Approved final / Partially / Fully Received — sama dengan Dashboard Price "
                   "Control (Waiting Approval, Draft, Cancelled, Rejected tidak dinilai). Harga kontrak = harga yang berlaku pada tanggal PO "
                   "(termasuk riwayat perubahan harga resmi). Status PO Approved TIDAK berarti penyimpangan harga disetujui.",
        drill=_drill("po", "po_id")),
]
for _s in SPECS:
    register(_s)
