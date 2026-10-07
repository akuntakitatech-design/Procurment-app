"""KPI Finance — engine Invoice Vendor & DP Supplier existing (tanpa ledger kedua).

Sisa kewajiban invoice (canonical): remaining = amount - dp_allocated_total - paid_total.
DP bukan pembayaran invoice aktual: payment_status / settlement_status tetap dari engine existing.
"""
from __future__ import annotations

from . import scope as S

EPS = 0.005


def remaining(inv):
    return float(inv.get("amount") or 0) - float(inv.get("dp_allocated_total") or 0) - float(inv.get("paid_total") or 0)


def outstanding(inv):
    return max(remaining(inv), 0.0)


INV_KINDS = {
    "unpaid": lambda i: remaining(i) > EPS,
    "payable": lambda i: remaining(i) > EPS,
    "due_soon": lambda i: remaining(i) > EPS and i.get("due_state") == "Jatuh Tempo",
    "overdue": lambda i: remaining(i) > EPS and i.get("due_state") == "Lewat Jatuh Tempo",
}
BILL_FULL = "Sudah Ditagihkan Penuh"
DO_KINDS = {"unbilled": lambda d: d.get("billing_status") != BILL_FULL and float(d.get("remaining") or 0) > EPS}
DP_KINDS = {
    "dp_paid": lambda p: float(p.get("paid_amount") or 0) > EPS,
    "dp_unallocated": lambda p: float(p.get("dp_available") or 0) > EPS,
}


def _cv(rows, fn):
    return {"count": len(rows), "value": round(sum(fn(r) for r in rows), 2)}


def filter_invoices(invs, f: S.Filters):
    """Saldo: invoice bertanggal <= tanggal akhir filter (termasuk periode sebelumnya)."""
    return [i for i in invs if S.upto(i, "invoice_date", f) and S.match_dims(i, f)]


def filter_invoices_period(invs, f: S.Filters):
    """Aktivitas: invoice diterima DI DALAM periode."""
    return [i for i in invs if S.in_period(i, "invoice_date", f) and S.match_dims(i, f)]


def filter_dos(dos, f: S.Filters):
    """Saldo: DO bertanggal <= tanggal akhir filter."""
    return [d for d in dos if S.upto(d, "date", f) and S.match_dims(d, f)]


def filter_dps(dps, f: S.Filters, po_by_id, dated=True):
    """DP mengikuti PO sumbernya (divisi/project dari lineage PO bila tersedia).
    dated=True -> saldo: DP PO bertanggal <= tanggal akhir filter; dated=False -> hanya dimensi (aktivitas memakai
    tanggal bayar DP, bukan tanggal PO)."""
    out = []
    for p in dps:
        ref = po_by_id.get(p.get("po_id")) or p
        if (not dated or S.in_range(p, "po_date", None, f.date_to)) and S.match_dims(ref, f) and \
                (not f.supplier_id or p.get("supplier_id") == f.supplier_id):
            out.append(p)
    return out


# ---- Rekonstruksi posisi historis (tanggal akhir filter < hari ini) — engine existing, read-only ------------
# Invoice : invoice_date <= cut-off ; pembayaran bertanggal <= cut-off yang AKTIF pada cut-off (batal SETELAH cut-off
#           = masih aktif saat itu) ; alokasi DP efektif = max(tanggal invoice, tanggal alokasi dicatat) <= cut-off ;
#           status jatuh tempo dibanding cut-off. Field current (remaining/paid_total/payment_status) TIDAK dipakai.
# DO      : tertagih = alokasi DO pada invoice bertanggal <= cut-off.
# DP      : dibayar = pembayaran DP disetujui bertanggal <= cut-off (batal setelah cut-off tetap dihitung);
#           terpakai = alokasi DP efektif <= cut-off.
def _active_at(pay, cutoff):
    if str(pay.get("date") or "")[:10] > cutoff:
        return False
    return pay.get("status") == "Aktif" or (bool(pay.get("cancelled_at")) and S.local_day(pay.get("cancelled_at")) > cutoff)


def dp_effective_day(alloc, inv_day):
    """Tanggal efektif alokasi DP = max(tanggal invoice, tanggal alokasi dicatat [WIB])."""
    return max(str(inv_day or "")[:10], S.local_day(alloc.get("created_at")))


async def _inv_days(server, inv_ids, known=None):
    known = dict(known or {})
    miss = [i for i in inv_ids if i and i not in known]
    if miss:
        for v in await server.db.vendor_invoices.find({"id": {"$in": miss}}, {"_id": 0, "id": 1, "invoice_date": 1}).to_list(None):
            known[v["id"]] = str(v.get("invoice_date") or "")[:10]
    return known


async def invoices_as_of(server, invs, cutoff):
    from datetime import date as _date

    import vendor_invoice_layer as VIL
    invs = [i for i in invs if i.get("id") and str(i.get("invoice_date") or "")[:10] <= cutoff]
    ids = [i["id"] for i in invs]
    if not ids:
        return []
    pays = await server.db.vendor_invoice_payments.find({"invoice_id": {"$in": ids}}, {"_id": 0}).to_list(None)
    dps = await server.db.vendor_invoice_dp_allocations.find(
        {"invoice_id": {"$in": ids}}, {"_id": 0, "invoice_id": 1, "amount": 1, "created_at": 1}).to_list(None)
    days = {i["id"]: str(i.get("invoice_date") or "")[:10] for i in invs}
    paid, dp = {}, {}
    for p in pays:
        if _active_at(p, cutoff):
            paid[p["invoice_id"]] = paid.get(p["invoice_id"], 0.0) + float(p.get("amount") or 0)
    for a in dps:
        if dp_effective_day(a, days.get(a["invoice_id"])) <= cutoff:
            dp[a["invoice_id"]] = dp.get(a["invoice_id"], 0.0) + float(a.get("amount") or 0)
    td = _date.fromisoformat(cutoff)
    out = []
    for i in invs:
        r = {**i, "paid_total": round(paid.get(i["id"], 0.0), 2), "dp_allocated_total": round(dp.get(i["id"], 0.0), 2)}
        r["payment_status"] = VIL.pay_status(float(r.get("amount") or 0), r["paid_total"], r["dp_allocated_total"])
        r["remaining"] = round(remaining(r), 2)
        r["due_state"] = VIL.due_state(r, td)
        r["as_of"] = cutoff
        out.append(r)
    return out


async def dos_as_of(server, dos, cutoff):
    import vendor_invoice_layer as VIL
    dos = [d for d in dos if d.get("do_id") and str(d.get("date") or "")[:10] <= cutoff]
    ids = [d["do_id"] for d in dos]
    if not ids:
        return []
    allocs = await server.db.vendor_invoice_allocations.find({"do_id": {"$in": ids}}, {"_id": 0, "do_id": 1, "invoice_id": 1, "amount": 1}).to_list(None)
    dates = await _inv_days(server, list({a.get("invoice_id") for a in allocs if a.get("invoice_id")}))
    billed = {}
    for a in allocs:
        if (dates.get(a.get("invoice_id")) or "9999") <= cutoff:
            billed[a["do_id"]] = billed.get(a["do_id"], 0.0) + float(a.get("amount") or 0)
    out = []
    for d in dos:
        b, v = round(billed.get(d["do_id"], 0.0), 2), float(d.get("do_value") or 0)
        out.append({**d, "billed": b, "remaining": round(v - b, 2), "billing_status": VIL.bill_status(v, b), "as_of": cutoff})
    return out


def _dp_paid_at(p, lo, hi):
    """Pembayaran DP yang berstatus 'Sudah Dibayar' pada tanggal hi dan tanggal bayarnya di [lo, hi]."""
    import supplier_dp_layer as SDP
    day = str(p.get("payment_date") or "")[:10]
    if not day or day > hi or (lo and day < lo):
        return False
    if p.get("status") == SDP.ST_APPROVED:
        return True
    return p.get("status") == SDP.ST_CANCELLED and bool(p.get("approved_at")) and S.local_day(p.get("approved_at")) <= hi \
        and S.local_day(p.get("cancelled_at")) > hi


async def dps_as_of(server, dps, cutoff, lo=None):
    """lo=None -> posisi s/d cut-off (dibayar, terpakai, tersedia); lo=tanggal -> dibayar DI DALAM [lo, cut-off]."""
    po_ids = [p["po_id"] for p in dps if p.get("po_id")]
    if not po_ids:
        return []
    pays = await server.db.supplier_dp_payments.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(None)
    allocs = await server.db.vendor_invoice_dp_allocations.find(
        {"po_id": {"$in": po_ids}}, {"_id": 0, "po_id": 1, "invoice_id": 1, "amount": 1, "created_at": 1}).to_list(None)
    dates = await _inv_days(server, list({a.get("invoice_id") for a in allocs if a.get("invoice_id")}))
    paid, used = {}, {}
    for p in pays:
        if _dp_paid_at(p, lo, cutoff):
            paid[p["po_id"]] = paid.get(p["po_id"], 0.0) + float(p.get("amount") or 0)
    for a in allocs:
        inv_day = dates.get(a.get("invoice_id"))
        if inv_day and dp_effective_day(a, inv_day) <= cutoff:
            used[a["po_id"]] = used.get(a["po_id"], 0.0) + float(a.get("amount") or 0)
    return [{**p, "paid_amount": round(paid.get(p["po_id"], 0.0), 2), "dp_used": round(used.get(p["po_id"], 0.0), 2),
             "dp_available": round(paid.get(p["po_id"], 0.0) - used.get(p["po_id"], 0.0), 2), "as_of": cutoff} for p in dps]


def kpis(invs, dos, dps, invs_period=None, dps_period=None):
    """invs/dos/dps = SALDO s/d tanggal akhir filter (sudah direkonstruksi bila historis); *_period = aktivitas periode.
    dps None = tanpa izin DP Supplier."""
    out = {
        "invoice_unbilled": _cv([d for d in dos if DO_KINDS["unbilled"](d)], lambda d: float(d.get("remaining") or 0)),
        "invoice_received": _cv(invs if invs_period is None else invs_period, lambda i: float(i.get("amount") or 0)),
    }
    for k in ("unpaid", "due_soon", "overdue"):
        out[f"invoice_{k}" if k == "unpaid" else k] = _cv([i for i in invs if INV_KINDS[k](i)], outstanding)
    # Sisa Hutang Supplier = Σ max(amount - dp_allocated_total - paid_total, 0) seluruh invoice aktif yang visible
    out["payable"] = {"count": len([i for i in invs if INV_KINDS["payable"](i)]), "value": round(sum(outstanding(i) for i in invs), 2)}
    if dps is not None:
        dpp = dps if dps_period is None else dps_period
        out["dp_paid"] = _cv([p for p in dpp if DP_KINDS["dp_paid"](p)], lambda p: float(p.get("paid_amount") or 0))
        out["dp_unallocated"] = _cv([p for p in dps if DP_KINDS["dp_unallocated"](p)], lambda p: max(float(p.get("dp_available") or 0), 0.0))
    else:
        out["dp_paid"] = out["dp_unallocated"] = None
    return out
