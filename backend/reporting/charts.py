"""Tren bulanan, komposisi Status Dokumen PO, ranking supplier."""
from __future__ import annotations

from datetime import date

import receipt_control_layer as RC

from . import procurement as P
from . import scope as S

STATUS_ORDER = ["Draft", RC.DOC_WAITING_A1, RC.DOC_READY_A2, RC.DOC_WAITING_A2, "Waiting Approval",
                "Approved", "Closed", "Rejected", "Cancelled"]


def trend_window(f: S.Filters, months=12):
    end = date.fromisoformat(f.date_to or f.today)
    start = S.shift_month(end, -(months - 1))
    return start.isoformat(), S.month_bounds(end)[1]


def trend(po_rows, invs, f: S.Filters, perm, months=12):
    """Nilai PO (Grand Total PO valid, per tanggal PO) & Nilai Invoice (amount, per tanggal invoice) per bulan.
    Mengikuti filter Divisi/Project/Supplier; jendela = N bulan s/d bulan Tanggal Akhir."""
    lo, hi = trend_window(f, months)
    start = date.fromisoformat(lo)
    keys = [S.shift_month(start, i).isoformat()[:7] for i in range(months)]
    b = {k: {"month": k, "po_value": 0.0, "po_count": 0, "invoice_value": 0.0, "invoice_count": 0} for k in keys}
    for r in po_rows:
        k = S.day(r, "date")[:7]
        if k in b and P.po_valid(r) and S.match_dims(r, f) and S.in_range(r, "date", lo, hi):
            b[k]["po_count"] += 1
            b[k]["po_value"] += float(r.get("grand_total") or 0)
    for i in invs or []:
        k = S.day(i, "invoice_date")[:7]
        if k in b and S.match_dims(i, f):
            b[k]["invoice_count"] += 1
            b[k]["invoice_value"] += float(i.get("amount") or 0)
    out = []
    for k in keys:
        x = b[k]
        out.append({"month": k, "po_count": x["po_count"], "invoice_count": x["invoice_count"] if invs is not None else None,
                    "po_value": round(x["po_value"], 2) if perm["price"] else None,
                    "invoice_value": round(x["invoice_value"], 2) if invs is not None else None})
    return {"months": months, "metric": "grand_total", "from": lo, "to": hi, "series": out}


def composition(po_rows):
    """Jumlah PO per Status Dokumen (derived) — sama dgn list PO pada filter yang sama."""
    cnt = {}
    for r in po_rows:
        k = r.get("document_status") or "-"
        cnt[k] = cnt.get(k, 0) + 1
    order = STATUS_ORDER + sorted(k for k in cnt if k not in STATUS_ORDER)
    return {"total": len(po_rows), "items": [{"status": k, "count": cnt[k]} for k in order if cnt.get(k)]}


def supplier_rank(po_rows, perm, limit=5):
    """Top supplier berdasarkan Nilai PO valid (Grand Total). Tanpa izin harga: urut jumlah PO, nilai tidak dikirim."""
    agg = {}
    for r in po_rows:
        if not P.po_valid(r) or not r.get("supplier_id"):
            continue
        a = agg.setdefault(r["supplier_id"], {"supplier_id": r["supplier_id"], "supplier_name": r.get("supplier_name") or "-",
                                               "count": 0, "value": 0.0})
        a["count"] += 1
        a["value"] += float(r.get("grand_total") or 0)
    rows = sorted(agg.values(), key=lambda a: ((a["value"] if perm["price"] else a["count"]), a["count"]), reverse=True)[:limit]
    for a in rows:
        a["value"] = round(a["value"], 2) if perm["price"] else None
    return {"metric": "po_value" if perm["price"] else "po_count", "items": rows}
