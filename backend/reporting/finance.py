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
    return [i for i in invs if S.in_period(i, "invoice_date", f) and S.match_dims(i, f)]


def filter_dos(dos, f: S.Filters):
    return [d for d in dos if S.in_period(d, "date", f) and S.match_dims(d, f)]


def filter_dps(dps, f: S.Filters, po_by_id):
    """DP mengikuti PO sumbernya (periode = tanggal PO; divisi/project dari lineage PO bila tersedia)."""
    out = []
    for p in dps:
        ref = po_by_id.get(p.get("po_id")) or p
        if S.in_range(p, "po_date", f.date_from, f.date_to) and S.match_dims(ref, f) and \
                (not f.supplier_id or p.get("supplier_id") == f.supplier_id):
            out.append(p)
    return out


def kpis(invs, dos, dps):
    """invs/dos/dps sudah tersaring scope + filter. dps None = tanpa izin DP Supplier."""
    out = {
        "invoice_unbilled": _cv([d for d in dos if DO_KINDS["unbilled"](d)], lambda d: float(d.get("remaining") or 0)),
        "invoice_received": _cv(invs, lambda i: float(i.get("amount") or 0)),
    }
    for k in ("unpaid", "due_soon", "overdue"):
        out[f"invoice_{k}" if k == "unpaid" else k] = _cv([i for i in invs if INV_KINDS[k](i)], outstanding)
    # Sisa Hutang Supplier = Σ max(amount - dp_allocated_total - paid_total, 0) seluruh invoice aktif yang visible
    out["payable"] = {"count": len([i for i in invs if INV_KINDS["payable"](i)]), "value": round(sum(outstanding(i) for i in invs), 2)}
    if dps is not None:
        out["dp_paid"] = _cv([p for p in dps if DP_KINDS["dp_paid"](p)], lambda p: float(p.get("paid_amount") or 0))
        out["dp_unallocated"] = _cv([p for p in dps if DP_KINDS["dp_unallocated"](p)], lambda p: max(float(p.get("dp_available") or 0), 0.0))
    else:
        out["dp_paid"] = out["dp_unallocated"] = None
    return out
