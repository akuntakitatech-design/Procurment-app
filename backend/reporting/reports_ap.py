"""P5 — Reporting Invoice, Pembayaran & Hutang Vendor pada Pusat Laporan (READ-ONLY).

Tidak ada engine kedua — seluruh angka memakai sumber yang SAMA dengan modul Invoice Vendor & Dashboard:
  * Invoice     = server.VENDOR_INVOICE_REPORT["invoices"] (visibilitas divisi existing: invoice tampil bila SELURUH DO-nya
                  dalam cakupan user; enrich existing: supplier, No. DO, lineage divisi/proyek, sisa, status).
  * Posisi      = rumus kanonik existing: Sisa = Nilai Invoice − DP Dialokasikan − Pembayaran Aktual (reporting.finance).
                  Tanggal Posisi lampau -> rekonstruksi as-of WIB existing (reporting.finance.invoices_as_of): invoice bertanggal
                  <= cut-off, pembayaran bertanggal <= cut-off yang AKTIF pada cut-off (dibatalkan SESUDAH cut-off = masih
                  aktif), alokasi DP efektif = max(tgl invoice, tgl alokasi dicatat) <= cut-off. Sama persis dengan Dashboard.
  * Multi-DO    = SATU baris per invoice (nilai header invoice); DO hanya informasi (No. DO) -> tidak ada penggandaan.
  * DP Supplier = bukan pembayaran: kolom terpisah; DP yang belum dialokasikan ke invoice TIDAK mengurangi hutang.
  * Divisi / Proyek mengikuti lineage DO -> PO. Filter memasukkan invoice bila salah satu DO cocok; nilai invoice tidak
                  dipecah; ringkasan mengelompokkan invoice multi-divisi/proyek ke "Lebih dari satu ..." (tanpa hitung ganda).
  * Invoice tidak memiliki status batal (hapus permanen, hanya tanpa pembayaran aktif) -> invoice terhapus tidak ada di
    laporan; nilai invoice tidak berversi -> posisi historis memakai nilai invoice kini (keterbatasan engine existing,
    sama dengan Dashboard). Pembayaran: Aktif / Dibatalkan (alasan) mengikuti engine existing.
Izin: seluruh laporan wajib invoice.view (nominal invoice = hak lihat modul Invoice Vendor existing); cakupan divisi server-side.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException

from reporting import finance as F
from reporting import scope as S
from reporting.registry import Column, Filter, ReportSpec, register

G = "hutang"
PERM = "invoice.view"
EPS = F.EPS
FAR = "9999-12-31"
PAY_ST = ("Belum Dibayar", "Dibayar Sebagian", "Lunas")
BUCKETS = (("nodue", "Tanpa Jatuh Tempo"), ("current", "Belum Jatuh Tempo"), ("d1_30", "Lewat 1–30 Hari"),
           ("d31_60", "Lewat 31–60 Hari"), ("d61_90", "Lewat 61–90 Hari"), ("d90", "Lewat > 90 Hari"))
MULTI_DIV, NONE_DIV = "Lebih dari satu divisi", "Tanpa divisi"
MULTI_PROJ, NONE_PROJ = "Lebih dari satu proyek", "Tanpa proyek"

F_FROM_INV, F_TO_INV = Filter("date_from", "Tanggal Awal (Tgl Invoice)", "date"), Filter("date_to", "Tanggal Akhir (Tgl Invoice)", "date")
F_CUT = Filter("date_to", "Tanggal Posisi (Cut-off)", "date")
F_DIV, F_PROJ, F_SUP = Filter("division_id", "Divisi", "division"), Filter("project_id", "Proyek", "project"), Filter("supplier_id", "Supplier", "supplier")
F_INV_ID = Filter("invoice_id", "Invoice", "text", hidden=True)
# Drill dari ringkasan per divisi/proyek: baris Outstanding = isi kelompok yang sama persis (tanpa/hanya invoice multi-dimensi)
GROUP_SCOPE = (("division_single", "Hanya invoice satu divisi"), ("division_multi", "Lebih dari satu divisi"),
               ("division_none", "Tanpa divisi"), ("project_single", "Hanya invoice satu proyek"),
               ("project_multi", "Lebih dari satu proyek"), ("project_none", "Tanpa proyek"))
F_GROUP_SCOPE = Filter("group_scope", "Kelompok Ringkasan", "select", GROUP_SCOPE, hidden=True)


def _in_group_scope(i, gs):
    if not gs:
        return True
    dim, kind = gs.split("_", 1)
    n = len(i.get(f"trace_{dim}_ids") or [])
    return {"single": n == 1, "multi": n > 1, "none": n == 0}[kind]  # riwayat pembayaran satu invoice (tautan dari laporan lain)
POS_NOTE = ("Posisi per Tanggal Posisi (WIB; kosong = hari ini) — sama dengan Dashboard. Sisa Hutang = Nilai Invoice − DP "
            "Dialokasikan − Pembayaran Aktual; pembayaran bertanggal ≤ Tanggal Posisi yang aktif pada tanggal tersebut (pembatalan "
            "sesudahnya tidak mengurangi posisi). DP yang belum dialokasikan ke invoice tidak mengurangi hutang. Satu baris per "
            "invoice (invoice multi-DO tidak digandakan). Invoice yang dihapus tidak tercatat; nilai invoice = nilai kini.")


# ----------------------------------------------------------------------------------------------- util
def _fmt_day(v):
    v = str(v or "")[:10]
    return f"{v[8:10]}-{v[5:7]}-{v[0:4]}" if len(v) == 10 else "-"


def _r(v):
    return round(float(v or 0), 2)


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _vi(server):
    vi = getattr(server, "VENDOR_INVOICE_REPORT", None)
    if not vi:
        raise HTTPException(503, "Modul Invoice Vendor belum tersedia.")
    return vi


def _filters(server, user, p, default_month=False):
    df, dt = p.get("date_from") or None, p.get("date_to") or None
    period = None if (df or dt or default_month) else "all"
    return S.resolve_filters(server, user, df, dt, p.get("division_id"), p.get("project_id"), p.get("supplier_id"), period)


async def _candidates(server, user, f):
    """Invoice visible (cakupan divisi existing) yang cocok dimensi filter (divisi/proyek lineage, supplier)."""
    return [i for i in await _vi(server)["invoices"](user) if S.match_dims(i, f)]


async def _at(server, invs, day, today):
    """Posisi invoice bertanggal <= day: lampau -> rekonstruksi as-of existing; selain itu nilai engine kini."""
    rows = [i for i in invs if S.day(i, "invoice_date") <= day]
    return await F.invoices_as_of(server, rows, day) if day < today else rows


async def _position(server, user, p):
    """Posisi s/d Tanggal Posisi = predikat & rekonstruksi Dashboard (reporting.service.dashboard)."""
    f = _filters(server, user, {**p, "date_from": None})
    cut = S.asof(f)
    invs = F.filter_invoices(await _candidates(server, user, f), f)
    if S.is_historical(f):
        invs = await F.invoices_as_of(server, invs, cut)
    return f, cut, invs


def _dim_label(i, dim, multi, none):
    """Label baris: satu nama; invoice lintas dimensi diberi label "Lebih dari satu ..." (+ nama) — nilai tidak dipecah."""
    ids, names = i.get(f"trace_{dim}_ids") or [], i.get(f"trace_{dim}") or "-"
    return none if not ids else names if len(ids) == 1 else f"{multi}: {names}"


def _div_label(i):
    return _dim_label(i, "division", MULTI_DIV, NONE_DIV)


def _proj_label(i):
    return _dim_label(i, "project", MULTI_PROJ, NONE_PROJ)


async def _att_counts(server, inv_ids):
    if not inv_ids:
        return {}, {}
    atts = await server.db.attachments.find({"invoice_id": {"$in": list(inv_ids)}, "is_deleted": False},
                                            {"_id": 0, "entity": 1, "entity_id": 1, "invoice_id": 1}).to_list(None)
    inv, pay = {}, {}
    for a in atts:
        if a.get("entity") == "invoice":
            inv[a["invoice_id"]] = inv.get(a["invoice_id"], 0) + 1
        elif a.get("entity") == "invoice_payment":
            pay[a.get("entity_id")] = pay.get(a.get("entity_id"), 0) + 1
    return inv, pay


def _inv_head(i):
    return {"id": i["id"], "no": i.get("no") or "-", "invoice_no": i.get("invoice_no") or "-",
            "invoice_date": S.day(i, "invoice_date") or None, "received_date": S.day(i, "received_date") or None,
            "due_date": S.day(i, "due_date") or None, "supplier_id": i.get("supplier_id"), "supplier": i.get("supplier_name") or "-",
            "do_nos": i.get("do_nos") or "-", "do_count": len(i.get("do_ids") or []),
            "division": _div_label(i), "project": _proj_label(i)}


def _money(i):
    paid, dp = _r(i.get("paid_total")), _r(i.get("dp_allocated_total"))
    return {"dpp": _r(i.get("dpp")), "tax_amount": _r(i.get("tax_amount")), "amount": _r(i.get("amount")),
            "dp_allocated": dp, "paid": paid, "remaining": _r(F.outstanding(i))}


def _aging(i, cut):
    dd = S.day(i, "due_date")
    if not dd:
        return None, "nodue"
    n = _days(dd, cut)
    if n <= 0:
        return 0, "current"
    return n, "d1_30" if n <= 30 else "d31_60" if n <= 60 else "d61_90" if n <= 90 else "d90"


def _drill_rc(key, **qs):
    q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
    return f"/report-center/{key}" + (f"?{q}" if q else "")


# ----------------------------------------------------------------------------------------------- 1. Register Invoice
REG_STATUS = (("outstanding", "Belum Lunas (masih bersaldo)"), ("unpaid", "Belum Dibayar"), ("partial", "Dibayar Sebagian"),
              ("paid", "Lunas"), ("overdue", "Lewat Jatuh Tempo (bersaldo)"))


async def invoice_register(server, user, p):
    f = _filters(server, user, p)
    cut = S.asof(f)
    invs = F.filter_invoices_period(await _candidates(server, user, f), f)
    if S.is_historical(f):
        invs = await F.invoices_as_of(server, invs, cut)
    if p.get("invoice_id"):
        invs = [i for i in invs if i["id"] == p["invoice_id"]]
    pays = await server.db.vendor_invoice_payments.find({"invoice_id": {"$in": [i["id"] for i in invs]}},
                                                         {"_id": 0}).to_list(None) if invs else []
    eff = cut if S.is_historical(f) else FAR
    cnt = {}
    for x in pays:
        if F._active_at(x, eff):
            cnt[x["invoice_id"]] = cnt.get(x["invoice_id"], 0) + 1
    att, _ = await _att_counts(server, [i["id"] for i in invs])
    st = p.get("status")
    out = []
    for i in invs:
        rem = F.remaining(i)
        days, bucket = _aging(i, cut)
        overdue = rem > EPS and bucket not in ("nodue", "current")
        if st == "outstanding" and not rem > EPS or st == "overdue" and not overdue or \
                st in ("unpaid", "partial", "paid") and i.get("payment_status") != PAY_ST[("unpaid", "partial", "paid").index(st)]:
            continue
        out.append({**_inv_head(i), **_money(i), "payment_count": cnt.get(i["id"], 0),
                    "payment_status": i.get("payment_status") or "-",
                    "settlement_status": "Lunas" if rem <= EPS else "Belum Lunas",
                    "due_state": "Lunas" if rem <= EPS else dict(BUCKETS)[bucket],
                    "days_overdue": days if rem > EPS else None,
                    "diff_status": i.get("diff_status") or "-", "attachments": att.get(i["id"], 0)})
    out.sort(key=lambda r: (r["invoice_date"] or "", r["no"]))
    return out


# ----------------------------------------------------------------------------------------------- 2. Monitoring Pembayaran
PAY_FILTER = (("active", "Aktif"), ("cancelled", "Dibatalkan"))


async def payments(server, user, p):
    f = _filters(server, user, p)
    invs = {i["id"]: i for i in await _candidates(server, user, f)}
    if p.get("invoice_id"):
        invs = {k: v for k, v in invs.items() if k == p["invoice_id"]}
    rows = await server.db.vendor_invoice_payments.find({"invoice_id": {"$in": list(invs)}}, {"_id": 0}).to_list(None) if invs else []
    hist = bool(f.date_to and f.date_to < f.today)
    eff = f.date_to if hist else FAR
    by = {}
    for x in rows:
        by.setdefault(x["invoice_id"], []).append(x)
    _, att = await _att_counts(server, list(by))
    out, st = [], p.get("status")
    for iid, xs in by.items():
        i, cum = invs[iid], 0.0
        for n, x in enumerate(sorted(xs, key=lambda x: (str(x.get("date") or ""), str(x.get("created_at") or ""))), 1):
            active = F._active_at(x, eff)
            if active:
                cum += float(x.get("amount") or 0)
            if not S.in_period(x, "date", f):
                continue
            if st == "active" and x.get("status") != "Aktif" or st == "cancelled" and x.get("status") == "Aktif":
                continue
            cancelled = x.get("status") != "Aktif"
            out.append({"invoice_id": iid, "payment_id": x.get("id"), "no": i.get("no") or "-", "invoice_no": i.get("invoice_no") or "-",
                        "supplier": i.get("supplier_name") or "-", "invoice_date": S.day(i, "invoice_date") or None,
                        "invoice_amount": _r(i.get("amount")), "seq": n, "date": S.day(x, "date") or None,
                        "amount": _r(x.get("amount")), "amount_effective": _r(x.get("amount")) if active else 0.0,
                        "cumulative": _r(cum) if active else None,
                        "reference": x.get("reference") or "-", "notes": x.get("notes") or "-",
                        "status": "Dibatalkan" if cancelled else "Aktif",
                        "cancelled_at": S.local_day(x.get("cancelled_at")) or None if cancelled else None,
                        "cancel_reason": (x.get("cancel_reason") or "-") if cancelled else "-",
                        "created_by": x.get("created_by_name") or x.get("created_by") or "-", "attachments": att.get(x.get("id"), 0),
                        "division": _div_label(i), "project": _proj_label(i)})
    out.sort(key=lambda r: (r["no"], r["seq"]))
    return out


# ----------------------------------------------------------------------------------------------- 3. Outstanding Hutang
async def outstanding(server, user, p):
    _f, cut, invs = await _position(server, user, p)
    out = []
    for i in invs:
        if not F.remaining(i) > EPS or not _in_group_scope(i, p.get("group_scope")):
            continue  # invoice lunas (termasuk tertutup DP penuh) bukan outstanding
        days, bucket = _aging(i, cut)
        out.append({**_inv_head(i), **_money(i), "payment_status": i.get("payment_status") or "-",
                    "due_state": dict(BUCKETS)[bucket], "days_overdue": days,
                    "overdue_amount": _r(F.outstanding(i)) if bucket not in ("nodue", "current") else 0.0})
    out.sort(key=lambda r: (r["supplier"], r["due_date"] or FAR, r["no"]))
    return out


GROUP_BY = (("supplier", "Per Supplier"), ("division", "Per Divisi"), ("project", "Per Proyek"))


def _group_key(i, by):
    if by == "division":
        ids = i.get("trace_division_ids") or []
        return (ids[0], i.get("trace_division") or ids[0]) if len(ids) == 1 else (("_multi", MULTI_DIV) if ids else ("_none", NONE_DIV))
    if by == "project":
        ids = i.get("trace_project_ids") or []
        return (ids[0], i.get("trace_project") or ids[0]) if len(ids) == 1 else (("_multi", MULTI_PROJ) if ids else ("_none", NONE_PROJ))
    return i.get("supplier_id") or "_none", i.get("supplier_name") or "-"


async def outstanding_summary(server, user, p):
    _f, cut, invs = await _position(server, user, p)
    by = p.get("group_by") or "supplier"
    agg = {}
    for i in invs:
        if not F.remaining(i) > EPS:
            continue
        k, label = _group_key(i, by)
        a = agg.setdefault(k, {"key": k, "no": label, "invoice_count": 0, "amount": 0.0, "dp_allocated": 0.0, "paid": 0.0,
                               "remaining": 0.0, "overdue_amount": 0.0, "oldest_due": None})
        _d, bucket = _aging(i, cut)
        o = F.outstanding(i)
        a["invoice_count"] += 1
        a["amount"] += float(i.get("amount") or 0)
        a["dp_allocated"] += float(i.get("dp_allocated_total") or 0)
        a["paid"] += float(i.get("paid_total") or 0)
        a["remaining"] += o
        a["overdue_amount"] += o if bucket not in ("nodue", "current") else 0.0
        dd = S.day(i, "due_date")
        if dd and (not a["oldest_due"] or dd < a["oldest_due"]):
            a["oldest_due"] = dd
    qs_key = {"supplier": "supplier_id", "division": "division_id", "project": "project_id"}[by]
    out = []
    for a in agg.values():
        for k in ("amount", "dp_allocated", "paid", "remaining", "overdue_amount"):
            a[k] = _r(a[k])
        a["dimension"] = dict(GROUP_BY)[by]
        base = {"date_to": p.get("date_to"), **{k: p.get(k) for k in ("division_id", "project_id", "supplier_id") if k != qs_key}}
        if by == "supplier":
            a["_to"] = None if a["key"] == "_none" else _drill_rc("ap-outstanding", supplier_id=a["key"], **base)
        elif a["key"].startswith("_"):  # kelompok multi / tanpa dimensi -> Outstanding berisi kelompok yang sama
            a["_to"] = _drill_rc("ap-outstanding", group_scope=f"{by}{a['key']}", **{**base, qs_key: p.get(qs_key)})
        else:  # satu divisi/proyek -> hanya invoice satu dimensi tsb (invoice multi tidak ikut, sama dengan angka kelompok)
            a["_to"] = _drill_rc("ap-outstanding", group_scope=f"{by}_single", **{**base, qs_key: a["key"]})
        out.append(a)
    out.sort(key=lambda r: (r["key"].startswith("_"), -r["remaining"], r["no"]))
    return out


# ----------------------------------------------------------------------------------------------- 4. Aging Hutang
AGING_LEVEL = (("invoice", "Per Invoice"), ("supplier", "Per Supplier"))


async def aging(server, user, p):
    _f, cut, invs = await _position(server, user, p)
    level, want = p.get("level") or "invoice", p.get("bucket")
    inv_rows, sup = [], {}
    for i in invs:
        if not F.remaining(i) > EPS:
            continue
        days, bucket = _aging(i, cut)
        if want and bucket != want:
            continue
        o = _r(F.outstanding(i))
        b = {f"b_{k}": (o if k == bucket else 0.0) for k, _ in BUCKETS}
        if level == "supplier":
            a = sup.setdefault(i.get("supplier_id") or "_none", {"supplier_id": i.get("supplier_id"), "supplier": i.get("supplier_name") or "-",
                                                                 "invoice_count": 0, "remaining": 0.0, **{k: 0.0 for k in b}})
            a["invoice_count"] += 1
            a["remaining"] += o
            for k, v in b.items():
                a[k] += v
            continue
        h = _inv_head(i)
        inv_rows.append({"id": h["id"], "no": h["no"], "invoice_no": h["invoice_no"], "supplier": h["supplier"],
                         "invoice_date": h["invoice_date"], "due_date": h["due_date"], "days_overdue": days,
                         "bucket": dict(BUCKETS)[bucket], "invoice_count": 1, **b, "remaining": o,
                         "division": h["division"], "project": h["project"]})
    if level == "supplier":
        out = []
        for a in sup.values():
            out.append({**{k: _r(v) if isinstance(v, float) else v for k, v in a.items()}, "no": None, "bucket": "-"})
        return sorted(out, key=lambda r: (-r["remaining"], r["supplier"]))
    return sorted(inv_rows, key=lambda r: (r["supplier"], -(r["days_overdue"] or -1), r["no"]))


# ----------------------------------------------------------------------------------------------- 5. Rekap per Supplier
def _sums(rows):
    out = {}
    for i in rows:
        a = out.setdefault(i.get("supplier_id") or "_none", {"name": i.get("supplier_name") or "-", "n": 0, "amount": 0.0, "paid": 0.0,
                                                             "dp": 0.0, "rem": 0.0, "open": 0})
        a["n"] += 1
        a["amount"] += float(i.get("amount") or 0)
        a["paid"] += float(i.get("paid_total") or 0)
        a["dp"] += float(i.get("dp_allocated_total") or 0)
        a["rem"] += F.remaining(i)
        a["open"] += 1 if F.remaining(i) > EPS else 0
    return out


async def _recap_window(server, cands, lo, hi, today, end_rows=None):
    """Mutasi per supplier pada [lo, hi]: Saldo Awal (posisi lo−1) + Invoice − Pembayaran Efektif − DP = Saldo Akhir (posisi hi)."""
    start = await _at(server, cands, (date.fromisoformat(lo) - timedelta(days=1)).isoformat(), today) if lo else []
    end = end_rows if end_rows is not None else await _at(server, cands, hi, today)
    s0, s1 = _sums(start), _sums(end)
    out = {}
    for k in sorted(set(s0) | set(s1)):
        a, b = s0.get(k) or {"n": 0, "amount": 0.0, "paid": 0.0, "dp": 0.0, "rem": 0.0, "open": 0}, s1.get(k) or {}
        b = {"name": a.get("name"), "n": 0, "amount": 0.0, "paid": 0.0, "dp": 0.0, "rem": 0.0, "open": 0, **b}
        out[k] = {"supplier_id": None if k == "_none" else k, "no": b["name"] or a.get("name") or "-",
                  "invoice_count": b["n"] - a["n"], "opening": _r(a["rem"]), "invoiced": _r(b["amount"] - a["amount"]),
                  "paid_period": _r(b["paid"] - a["paid"]), "dp_period": _r(b["dp"] - a["dp"]), "closing": _r(b["rem"]),
                  "total_billed": _r(b["amount"]), "total_paid": _r(b["paid"]), "total_dp": _r(b["dp"]), "open_count": b["open"]}
    return out


RECAP_NOTE = ("Periode = Tanggal Awal s/d Tanggal Akhir (WIB; kosong = bulan berjalan). Saldo Awal = posisi sehari sebelum Tanggal "
              "Awal; Saldo Akhir = posisi Tanggal Akhir = Outstanding Hutang per cut-off yang sama. Saldo Awal + Invoice Periode − "
              "Pembayaran Efektif Periode − DP Dialokasikan Periode = Saldo Akhir. Pembayaran Efektif = pembayaran baru dikurangi "
              "pembatalan pembayaran lama dalam periode; DP hanya yang benar-benar dialokasikan ke invoice (DP belum dialokasikan "
              "tidak mengurangi hutang). Invoice dihapus tidak tercatat; nilai invoice = nilai kini.")


async def supplier_recap(server, user, p):
    f = _filters(server, user, p, default_month=True)
    cands = await _candidates(server, user, f)
    _pf, _cut, end_rows = await _position(server, user, {**p, "date_to": f.date_to})  # = Outstanding per cut-off (paritas)
    rows = await _recap_window(server, cands, f.date_from, f.date_to, f.today, end_rows)
    period = f"{_fmt_day(f.date_from)} s/d {_fmt_day(f.date_to)}"
    out = [{**r, "period": period, "_to": _drill_rc("ap-outstanding", supplier_id=r["supplier_id"], date_to=f.date_to,
                                                     division_id=p.get("division_id"), project_id=p.get("project_id")) if r["supplier_id"] else None}
           for r in rows.values() if any(abs(r[k]) > EPS for k in ("opening", "invoiced", "paid_period", "dp_period", "closing"))]
    return sorted(out, key=lambda r: (-r["closing"], r["no"]))


def _months(lo, hi):
    d0, d1 = date.fromisoformat(lo), date.fromisoformat(hi)
    cur = d0
    while cur <= d1:
        nxt = S.shift_month(cur.replace(day=1), 1)
        yield cur.isoformat(), min(nxt - timedelta(days=1), d1).isoformat()
        cur = nxt


async def supplier_recap_monthly(server, user, p):
    f = _filters(server, user, p, default_month=True)
    if not f.date_from:
        raise HTTPException(400, "Tanggal Awal wajib diisi untuk rincian per bulan.")
    if len(list(_months(f.date_from, f.date_to))) > 36:
        raise HTTPException(400, "Rincian per bulan maksimal 36 bulan. Persempit periode.")
    cands = await _candidates(server, user, f)
    out = []
    for lo, hi in _months(f.date_from, f.date_to):
        for r in (await _recap_window(server, cands, lo, hi, f.today)).values():
            if any(abs(r[k]) > EPS for k in ("opening", "invoiced", "paid_period", "dp_period", "closing")):
                out.append({**r, "month": lo[:7], "period": f"{_fmt_day(lo)} s/d {_fmt_day(hi)}",
                            "_to": _drill_rc("ap-outstanding", supplier_id=r["supplier_id"], date_to=hi) if r["supplier_id"] else None})
    return sorted(out, key=lambda r: (r["no"], r["month"]))


# ----------------------------------------------------------------------------------------------- registrasi
def _drill_inv(idk="id"):
    return lambda r: {"label": r.get("no"), "to": f"/invoice/{r.get(idk)}"} if r.get(idk) else None


def _drill_to(r):
    return {"label": r.get("no"), "to": r["_to"]} if r.get("_to") else None


M = lambda k, lb, w=15, **kw: Column(k, lb, "money", total=True, width=w, **kw)  # noqa: E731
C_SUP, C_DIV, C_PROJ = Column("supplier", "Supplier", width=20), Column("division", "Divisi", width=14), Column("project", "Proyek", width=16)
BUCKET_COLS = tuple(M(f"b_{k}", lb, 13) for k, lb in BUCKETS)

SPECS = [
    ReportSpec(
        key="ap-invoice-register", group=G, title="Register Invoice Vendor",
        description="Invoice vendor per tanggal invoice: DO terkait, DPP, PPN, total, DP dialokasikan, pembayaran, sisa tagihan, "
                    "jatuh tempo, dan status. Invoice multi-DO = satu baris (tidak digandakan).",
        columns=(Column("no", "No. Internal", width=14), Column("invoice_no", "No. Invoice Vendor", width=16),
                 Column("invoice_date", "Tgl Invoice", "date", width=11), Column("received_date", "Tgl Diterima", "date", width=11),
                 C_SUP, Column("do_nos", "No. DO", width=20), Column("do_count", "Jumlah DO", "int", width=7), C_DIV, C_PROJ,
                 M("dpp", "DPP"), M("tax_amount", "PPN / Pajak", 13), M("amount", "Total Invoice"),
                 M("dp_allocated", "DP Dialokasikan", 14), M("paid", "Sudah Dibayar"), M("remaining", "Sisa Tagihan"),
                 Column("due_date", "Jatuh Tempo", "date", width=11), Column("due_state", "Status Jatuh Tempo", width=16),
                 Column("days_overdue", "Hari Lewat Jatuh Tempo", "int", width=9),
                 Column("payment_count", "Jumlah Pembayaran", "int", width=9), Column("payment_status", "Status Pembayaran", width=15),
                 Column("settlement_status", "Status Hutang", width=11), Column("diff_status", "Selisih Alokasi DO", width=12),
                 Column("attachments", "Lampiran", "int", width=8)),
        builder=invoice_register,
        filters=(F_FROM_INV, F_TO_INV, F_DIV, F_PROJ, F_SUP, Filter("status", "Status", "select", REG_STATUS), F_INV_ID),
        search_keys=("no", "invoice_no", "supplier", "do_nos", "division", "project"), permission=PERM,
        date_basis="Invoice bertanggal invoice dalam periode (WIB; kosong = semua). Pembayaran, DP, sisa, dan status = posisi per "
                   "Tanggal Akhir bila lampau (rekonstruksi as-of sama dengan Dashboard), selain itu posisi kini. Sisa Tagihan = "
                   "Total − DP Dialokasikan − Sudah Dibayar. Tanggal Diterima (invoice diterima) tidak berarti dibayar. Lampiran "
                   "dibuka dari detail invoice sesuai hak akses.",
        drill=_drill_inv()),
    ReportSpec(
        key="ap-payments", group=G, title="Monitoring Pembayaran Vendor",
        description="Pembayaran invoice vendor per tanggal bayar: parsial maupun sekaligus, referensi, status Aktif / Dibatalkan, "
                    "dan riwayat pembayaran per invoice (urutan & kumulatif).",
        columns=(Column("no", "No. Internal Invoice", width=14), Column("invoice_no", "No. Invoice Vendor", width=16), C_SUP,
                 Column("invoice_date", "Tgl Invoice", "date", width=11), Column("invoice_amount", "Total Invoice", "money", width=14),
                 Column("seq", "Pembayaran ke-", "int", width=7), Column("date", "Tgl Pembayaran", "date", width=11),
                 Column("amount", "Nilai Pembayaran", "money", width=14), M("amount_effective", "Nilai Efektif (Aktif)"),
                 Column("cumulative", "Kumulatif Dibayar", "money", width=14),
                 Column("reference", "Referensi (No. Transfer / Giro)", width=18), Column("notes", "Catatan", width=18),
                 Column("status", "Status", width=10), Column("cancelled_at", "Tgl Dibatalkan", "date", width=11),
                 Column("cancel_reason", "Alasan Pembatalan", width=18), Column("created_by", "Dicatat Oleh", width=14),
                 Column("attachments", "Lampiran", "int", width=8), C_DIV, C_PROJ),
        builder=payments,
        filters=(Filter("date_from", "Tanggal Awal (Tgl Bayar)", "date"), Filter("date_to", "Tanggal Akhir (Tgl Bayar)", "date"),
                 F_DIV, F_PROJ, F_SUP, Filter("status", "Status Pembayaran", "select", PAY_FILTER), F_INV_ID),
        search_keys=("no", "invoice_no", "supplier", "reference", "notes", "status"), permission=PERM,
        date_basis="Pembayaran bertanggal bayar dalam periode (WIB; kosong = semua). Nilai Efektif = pembayaran yang aktif per "
                   "Tanggal Akhir bila lampau (dibatalkan sesudahnya tetap efektif), selain itu status kini; pembayaran dibatalkan "
                   "bernilai efektif 0. DP Supplier bukan pembayaran invoice dan tidak ditampilkan. Rekening/metode bayar tidak dicatat "
                   "per pembayaran (hanya Referensi & Catatan), sehingga tidak ditampilkan.",
        drill=_drill_inv("invoice_id")),
    ReportSpec(
        key="ap-outstanding", group=G, title="Outstanding Hutang Vendor",
        description="Saldo hutang per invoice per Tanggal Posisi: total invoice − DP dialokasikan − pembayaran efektif. Invoice "
                    "lunas tidak ditampilkan.",
        columns=(Column("no", "No. Internal", width=14), Column("invoice_no", "No. Invoice Vendor", width=16), C_SUP,
                 Column("invoice_date", "Tgl Invoice", "date", width=11), Column("do_nos", "No. DO", width=20), C_DIV, C_PROJ,
                 M("amount", "Total Invoice"), M("dp_allocated", "DP Dialokasikan", 14), M("paid", "Sudah Dibayar"),
                 M("remaining", "Outstanding"), Column("due_date", "Jatuh Tempo", "date", width=11),
                 Column("due_state", "Umur", width=16), Column("days_overdue", "Hari Lewat Jatuh Tempo", "int", width=9),
                 M("overdue_amount", "Outstanding Lewat Jatuh Tempo"), Column("payment_status", "Status Pembayaran", width=15)),
        builder=outstanding, filters=(F_CUT, F_DIV, F_PROJ, F_SUP, F_GROUP_SCOPE),
        search_keys=("no", "invoice_no", "supplier", "do_nos", "division", "project"), permission=PERM, date_basis=POS_NOTE,
        drill=_drill_inv()),
    ReportSpec(
        key="ap-outstanding-summary", group=G, title="Outstanding Hutang Vendor — Ringkasan per Supplier / Divisi / Proyek",
        description="Saldo hutang per Tanggal Posisi dikelompokkan per supplier, divisi, atau proyek. Invoice multi-divisi / "
                    "multi-proyek dikelompokkan tersendiri sehingga tidak terhitung ganda.",
        columns=(Column("dimension", "Kelompok", width=11), Column("no", "Supplier / Divisi / Proyek", width=24),
                 Column("invoice_count", "Jumlah Invoice", "int", total=True, width=9), M("amount", "Total Invoice"),
                 M("dp_allocated", "DP Dialokasikan", 14), M("paid", "Sudah Dibayar"), M("remaining", "Outstanding"),
                 M("overdue_amount", "Outstanding Lewat Jatuh Tempo"), Column("oldest_due", "Jatuh Tempo Terlama", "date", width=11)),
        builder=outstanding_summary,
        filters=(F_CUT, Filter("group_by", "Kelompokkan", "select", GROUP_BY, default="supplier"), F_DIV, F_PROJ, F_SUP),
        search_keys=("no",), permission=PERM,
        date_basis=POS_NOTE + " Divisi/Proyek mengikuti lineage DO → PO; invoice yang DO-nya lintas divisi/proyek masuk kelompok "
                              "\"Lebih dari satu divisi/proyek\" (nilai tidak dipecah). Drill kelompok membuka Outstanding berisi invoice "
                              "kelompok yang sama persis.",
        drill=_drill_to),
    ReportSpec(
        key="ap-aging", group=G, title="Aging Hutang Vendor",
        description="Umur outstanding per Tanggal Posisi: belum jatuh tempo, lewat 1–30, 31–60, 61–90, > 90 hari, dan invoice tanpa "
                    "jatuh tempo (terpisah). Per invoice atau per supplier.",
        columns=(Column("no", "No. Internal", width=14), Column("invoice_no", "No. Invoice Vendor", width=16), C_SUP,
                 Column("invoice_date", "Tgl Invoice", "date", width=11), Column("due_date", "Jatuh Tempo", "date", width=11),
                 Column("days_overdue", "Hari Lewat Jatuh Tempo", "int", width=9), Column("bucket", "Kategori Umur", width=15),
                 Column("invoice_count", "Jumlah Invoice", "int", total=True, width=8), *BUCKET_COLS, M("remaining", "Total Outstanding")),
        builder=aging,
        filters=(F_CUT, Filter("level", "Tampilan", "select", AGING_LEVEL, default="invoice"), F_DIV, F_PROJ, F_SUP,
                 Filter("bucket", "Kategori Umur", "select", BUCKETS)),
        search_keys=("no", "invoice_no", "supplier", "bucket"), permission=PERM,
        date_basis=POS_NOTE + " Umur = Tanggal Posisi − Jatuh Tempo (hari kalender WIB); jatuh tempo tepat pada Tanggal Posisi = Belum "
                              "Jatuh Tempo.",
        drill=_drill_inv()),
    ReportSpec(
        key="ap-supplier-recap", group=G, title="Rekap Hutang per Supplier",
        description="Per supplier untuk periode: saldo awal, invoice periode, pembayaran efektif, DP dialokasikan, saldo akhir "
                    "(= outstanding per cut-off), jumlah invoice, total tagihan & total pembayaran kumulatif.",
        columns=(Column("no", "Supplier", width=22), Column("period", "Periode", width=20),
                 Column("invoice_count", "Jumlah Invoice Periode", "int", total=True, width=9), M("opening", "Saldo Awal"),
                 M("invoiced", "Invoice Periode"), M("paid_period", "Pembayaran Efektif Periode"), M("dp_period", "DP Dialokasikan Periode"),
                 M("closing", "Saldo Akhir (Outstanding)"), M("total_billed", "Total Tagihan s/d Akhir"),
                 M("total_paid", "Total Pembayaran s/d Akhir"), M("total_dp", "Total DP Dialokasikan s/d Akhir"),
                 Column("open_count", "Invoice Belum Lunas", "int", total=True, width=9)),
        builder=supplier_recap, filters=(Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date"), F_DIV, F_PROJ, F_SUP),
        search_keys=("no",), permission=PERM, date_basis=RECAP_NOTE, drill=_drill_to),
    ReportSpec(
        key="ap-supplier-recap-monthly", group=G, title="Rekap Hutang per Supplier — Rincian per Bulan",
        description="Mutasi hutang per supplier per bulan kalender: saldo awal, invoice, pembayaran efektif, DP dialokasikan, saldo akhir.",
        columns=(Column("no", "Supplier", width=22), Column("month", "Bulan", width=9), Column("period", "Periode", width=20),
                 Column("invoice_count", "Jumlah Invoice", "int", total=True, width=8), Column("opening", "Saldo Awal Bulan", "money", width=15),
                 M("invoiced", "Invoice"), M("paid_period", "Pembayaran Efektif"), M("dp_period", "DP Dialokasikan"),
                 Column("closing", "Saldo Akhir Bulan", "money", width=15)),
        builder=supplier_recap_monthly, filters=(Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date"), F_DIV, F_PROJ, F_SUP),
        search_keys=("no", "month"), permission=PERM,
        date_basis=RECAP_NOTE + " Per bulan: Saldo Awal Bulan + Invoice − Pembayaran Efektif − DP = Saldo Akhir Bulan (saldo tidak "
                                "dijumlahkan antar bulan).",
        drill=_drill_to),
]
for _s in SPECS:
    register(_s)
