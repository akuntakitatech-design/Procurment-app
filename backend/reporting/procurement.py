"""KPI Procurement. Status Dokumen PO = derived document_status existing (receipt_control_layer), tidak dihitung ulang."""
from __future__ import annotations

import doc_procurement
import pull_source_eligibility_layer as PSE
import receipt_control_layer as RC

from . import scope as S

VALID_PO = ("Approved", "Partially Received", "Fully Received")  # Nilai PO valid (sama dgn engine DP/Invoice)
WAITING = (RC.DOC_WAITING_A1, RC.DOC_READY_A2, RC.DOC_WAITING_A2, "Waiting Approval")
FULL = ("Diterima Penuh", "Over Receipt")


def doc(r):
    return r.get("document_status")


def po_valid(r):
    return r.get("status") in VALID_PO and r.get("cancelled") is not True and doc(r) not in ("Cancelled", "Rejected")


def po_late(r, td):
    eta = S.day(r, "eta")
    return doc(r) == "Approved" and r.get("receipt_status") not in FULL and bool(eta) and eta < td


# Satu definisi per KPI -> dipakai kartu Dashboard DAN filter drill-down list PO (rf_kind).
PO_KINDS = {
    "waiting_a1": lambda r, td: doc(r) == RC.DOC_WAITING_A1,
    "ready_a2": lambda r, td: doc(r) == RC.DOC_READY_A2,
    "waiting_a2": lambda r, td: doc(r) == RC.DOC_WAITING_A2,
    "waiting_approval": lambda r, td: doc(r) in WAITING,
    "approved": lambda r, td: doc(r) == "Approved",
    "not_received": lambda r, td: doc(r) == "Approved" and r.get("receipt_status") == "Belum Diterima",
    "partial": lambda r, td: doc(r) == "Approved" and r.get("receipt_status") == "Diterima Sebagian",
    "late": po_late,
    "valid": lambda r, td: po_valid(r),
}


async def load_po_rows(server, user, lo=None, hi=None, show_price=True):
    """PO dalam rentang tanggal [lo, hi] -> enrich batch (document_status/receipt_status/lineage) -> scope divisi.
    Periode diterapkan sebelum enrichment (bagian termahal)."""
    docs = [d for d in await server.db.po.find({}, {"_id": 0}).to_list(200000) if S.in_range(d, "date", lo, hi)]
    if not docs:
        return []
    m = await doc_procurement.maps()
    for d in docs:
        d["supplier_name"] = (m["suppliers"].get(d.get("supplier_id")) or {}).get("name")
        d["division_name"] = (m["divisions"].get(d.get("division_id")) or {}).get("name")
        if not show_price:
            d["grand_total"] = None
    rows = await RC.enrich_list(server, "po", docs)
    for r in rows:
        r.pop("items", None)
        r.pop("items_search", None)
    return await S.visible(server, "po", rows, user)


async def outstanding_doc_ids(server, module, ids):
    """MRO: qty - (alokasi RO + MI) > 0 ; RO: qty - alokasi PO > 0 (per baris, 2 query batch)."""
    if not ids:
        return set()
    coll, fk, targets = ("mro_lines", "mro_id", ["ro", "mi"]) if module == "mro" else ("ro_lines", "ro_id", ["po"])
    lines = await getattr(server.db, coll).find({fk: {"$in": list(ids)}}, {"_id": 0, "id": 1, fk: 1, "qty": 1}).to_list(1000000)
    lids = [ln["id"] for ln in lines if ln.get("id")]
    used = {}
    if lids:
        for a in await server.db.allocations.find({"source_line_id": {"$in": lids}, "target_type": {"$in": targets}},
                                                  {"_id": 0, "source_line_id": 1, "qty": 1}).to_list(2000000):
            used[a["source_line_id"]] = used.get(a["source_line_id"], 0.0) + float(a.get("qty") or 0)
    return {ln[fk] for ln in lines if float(ln.get("qty") or 0) - used.get(ln.get("id"), 0.0) > 1e-9}


async def open_requests(server, user, module, f: S.Filters):
    """MRO Belum Diproses / RO Belum Menjadi PO: dokumen eligible (aturan pull existing) yang masih punya sisa."""
    docs = [d for d in await getattr(server.db, module).find(PSE._request_query(), {"_id": 0}).to_list(200000)
            if S.in_period(d, "date", f)]
    if not docs:
        return []
    rows = await RC.enrich_list(server, module, docs)
    rows = [r for r in await S.visible(server, module, rows, user) if S.match_dims(r, f, supplier=False)]
    ids = await outstanding_doc_ids(server, module, [r["id"] for r in rows])
    return [r for r in rows if r["id"] in ids]


def cv(rows, price, key="grand_total"):
    return {"count": len(rows), "value": round(sum(float(r.get(key) or 0) for r in rows), 2) if price else None}


def kpis(po_rows, mro_rows, ro_rows, f: S.Filters, perm):
    td, price = f.today, perm["price"]
    out = {k: cv([r for r in po_rows if fn(r, td)], price) for k, fn in PO_KINDS.items() if k != "valid"}
    out["po_value"] = cv([r for r in po_rows if po_valid(r)], price)
    out["po_total"] = {"count": len(po_rows), "value": None}
    out["mro_open"] = {"count": len(mro_rows), "value": None} if perm["mro"] else None
    out["ro_open"] = {"count": len(ro_rows), "value": None} if perm["ro"] else None
    return out
