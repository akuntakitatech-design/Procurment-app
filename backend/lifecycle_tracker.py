"""End-to-end MRO -> RO -> PO -> DO -> MI lifecycle tracking.

The endpoint is intentionally registered on ``server.app`` because production_bootstrap
loads this module after ``server`` has already included its API router.
"""
from fastapi import Depends, HTTPException


STAGE_ORDER = ["mro", "ro", "po", "do", "mi"]
COLLECTIONS = {
    "mro": ("mro", "mro_lines", "mro_id"),
    "ro": ("ro", "ro_lines", "ro_id"),
    "po": ("po", "po_lines", "po_id"),
    "do": ("do", "do_lines", "do_id"),
    "mi": ("mi", "mi_lines", "mi_id"),
}


def _qty(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def _docs_by_ids(db, collection_name, ids):
    ids = list(dict.fromkeys(x for x in ids if x))
    if not ids:
        return []
    rows = await getattr(db, collection_name).find({"id": {"$in": ids}}, {"_id": 0}).to_list(2000)
    pos = {doc_id: i for i, doc_id in enumerate(ids)}
    rows.sort(key=lambda d: pos.get(d.get("id"), 999999))
    return rows


async def _source_mro_ids(server, entity, doc_id):
    """Resolve the root MRO documents for any lifecycle document."""
    db = server.db
    entity = entity.lower()
    if entity == "mro":
        return [doc_id]

    if entity not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Jenis transaksi tidak didukung")

    _, line_collection, foreign_key = COLLECTIONS[entity]
    lines = await getattr(db, line_collection).find({foreign_key: doc_id}, {"_id": 0}).to_list(2000)
    line_ids = [l.get("id") for l in lines if l.get("id")]

    if entity == "mi":
        allocs = await db.allocations.find(
            {"target_line_id": {"$in": line_ids}, "source_type": "mro"}, {"_id": 0}
        ).to_list(5000)
        return list(dict.fromkeys(a.get("source_doc_id") for a in allocs if a.get("source_doc_id")))

    if entity == "ro":
        allocs = await db.allocations.find(
            {"target_line_id": {"$in": line_ids}, "source_type": "mro"}, {"_id": 0}
        ).to_list(5000)
        return list(dict.fromkeys(a.get("source_doc_id") for a in allocs if a.get("source_doc_id")))

    # PO -> RO -> MRO
    if entity == "po":
        po_src = await db.allocations.find(
            {"target_line_id": {"$in": line_ids}, "source_type": "ro"}, {"_id": 0}
        ).to_list(5000)
        ro_line_ids = [a.get("source_line_id") for a in po_src if a.get("source_line_id")]
        mro_src = await db.allocations.find(
            {"target_line_id": {"$in": ro_line_ids}, "source_type": "mro"}, {"_id": 0}
        ).to_list(5000)
        return list(dict.fromkeys(a.get("source_doc_id") for a in mro_src if a.get("source_doc_id")))

    # DO -> PO -> RO -> MRO
    do_src = await db.allocations.find(
        {"target_line_id": {"$in": line_ids}, "source_type": "po"}, {"_id": 0}
    ).to_list(5000)
    po_line_ids = [a.get("source_line_id") for a in do_src if a.get("source_line_id")]
    po_src = await db.allocations.find(
        {"target_line_id": {"$in": po_line_ids}, "source_type": "ro"}, {"_id": 0}
    ).to_list(5000)
    ro_line_ids = [a.get("source_line_id") for a in po_src if a.get("source_line_id")]
    mro_src = await db.allocations.find(
        {"target_line_id": {"$in": ro_line_ids}, "source_type": "mro"}, {"_id": 0}
    ).to_list(5000)
    return list(dict.fromkeys(a.get("source_doc_id") for a in mro_src if a.get("source_doc_id")))


async def build_lifecycle(server, entity, doc_id):
    db = server.db
    entity = entity.lower()
    if entity not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Jenis transaksi tidak didukung")

    header_collection, _, _ = COLLECTIONS[entity]
    current = await getattr(db, header_collection).find_one({"id": doc_id}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    root_ids = await _source_mro_ids(server, entity, doc_id)

    # Direct MI has no MRO ancestry. Still return a useful one-stage lifecycle.
    if not root_ids:
        if entity == "mi":
            mi_lines = await db.mi_lines.find({"mi_id": doc_id}, {"_id": 0}).to_list(2000)
            qty_mi = sum(_qty(l.get("qty")) for l in mi_lines)
            return {
                "current": {"type": entity, "id": doc_id, "no": current.get("no"), "status": current.get("status")},
                "direct": True,
                "summary": {"request": 0, "ro": 0, "po": 0, "received": 0, "mi": qty_mi, "outstanding": 0},
                "stages": [
                    {"key": "mro", "label": "MRO", "state": "na", "status": "Direct", "qty": 0, "documents": []},
                    {"key": "ro", "label": "RO", "state": "na", "status": "Direct", "qty": 0, "documents": []},
                    {"key": "po", "label": "PO", "state": "na", "status": "Direct", "qty": 0, "documents": []},
                    {"key": "do", "label": "DO", "state": "na", "status": "Direct", "qty": 0, "documents": []},
                    {"key": "mi", "label": "MI", "state": "done", "status": "Posted", "qty": qty_mi,
                     "documents": [{"id": current.get("id"), "no": current.get("no"), "date": current.get("date"), "qty": qty_mi}]},
                ],
            }
        raise HTTPException(status_code=404, detail="Sumber MRO transaksi tidak ditemukan")

    mro_docs = await _docs_by_ids(db, "mro", root_ids)
    mro_lines = await db.mro_lines.find({"mro_id": {"$in": root_ids}}, {"_id": 0}).to_list(10000)
    mro_line_ids = [l.get("id") for l in mro_lines if l.get("id")]
    qty_request = sum(_qty(l.get("qty")) for l in mro_lines)

    ro_allocs = await db.allocations.find(
        {"source_line_id": {"$in": mro_line_ids}, "target_type": "ro"}, {"_id": 0}
    ).to_list(20000)
    ro_doc_ids = list(dict.fromkeys(a.get("target_doc_id") for a in ro_allocs if a.get("target_doc_id")))
    ro_line_ids = list(dict.fromkeys(a.get("target_line_id") for a in ro_allocs if a.get("target_line_id")))
    qty_ro = sum(_qty(a.get("qty")) for a in ro_allocs)

    po_allocs = await db.allocations.find(
        {"source_line_id": {"$in": ro_line_ids}, "target_type": "po"}, {"_id": 0}
    ).to_list(20000)
    po_doc_ids = list(dict.fromkeys(a.get("target_doc_id") for a in po_allocs if a.get("target_doc_id")))
    po_line_ids = list(dict.fromkeys(a.get("target_line_id") for a in po_allocs if a.get("target_line_id")))
    qty_po = sum(_qty(a.get("qty")) for a in po_allocs)

    do_allocs = await db.allocations.find(
        {"source_line_id": {"$in": po_line_ids}, "target_type": "do"}, {"_id": 0}
    ).to_list(20000)
    do_doc_ids = list(dict.fromkeys(a.get("target_doc_id") for a in do_allocs if a.get("target_doc_id")))
    qty_do = sum(_qty(a.get("qty")) for a in do_allocs)

    mi_allocs = await db.allocations.find(
        {"source_line_id": {"$in": mro_line_ids}, "target_type": "mi"}, {"_id": 0}
    ).to_list(20000)
    mi_doc_ids = list(dict.fromkeys(a.get("target_doc_id") for a in mi_allocs if a.get("target_doc_id")))
    qty_mi = sum(_qty(a.get("qty")) for a in mi_allocs)

    ro_docs = await _docs_by_ids(db, "ro", ro_doc_ids)
    po_docs = await _docs_by_ids(db, "po", po_doc_ids)
    do_docs = await _docs_by_ids(db, "do", do_doc_ids)
    mi_docs = await _docs_by_ids(db, "mi", mi_doc_ids)

    def docs_with_qty(docs, allocs, target_field="target_doc_id"):
        qty_by_doc = {}
        for a in allocs:
            key = a.get(target_field)
            if key:
                qty_by_doc[key] = qty_by_doc.get(key, 0) + _qty(a.get("qty"))
        return [{"id": d.get("id"), "no": d.get("no"), "date": d.get("date"), "status": d.get("status"),
                 "qty": qty_by_doc.get(d.get("id"), 0)} for d in docs]

    mro_qty_by_doc = {}
    for l in mro_lines:
        mro_qty_by_doc[l.get("mro_id")] = mro_qty_by_doc.get(l.get("mro_id"), 0) + _qty(l.get("qty"))
    mro_ref_docs = [{"id": d.get("id"), "no": d.get("no"), "date": d.get("date"),
                     "status": "Cancelled" if d.get("cancelled") else ("Open" if d.get("submitted") else "Draft"),
                     "qty": mro_qty_by_doc.get(d.get("id"), 0)} for d in mro_docs]

    po_statuses = [str(d.get("status") or "") for d in po_docs]

    if qty_request > 0 and qty_mi >= qty_request:
        mro_state, mro_status = "done", "Completed"
    elif qty_mi > 0:
        mro_state, mro_status = "partial", "Partial"
    elif any(d.get("submitted") for d in mro_docs):
        mro_state, mro_status = "active", "Open"
    else:
        mro_state, mro_status = "active", "Draft"

    if qty_ro <= 0:
        ro_state, ro_status = "pending", "Belum diproses"
    elif qty_po >= qty_ro and qty_ro > 0:
        ro_state, ro_status = "done", "Fully Ordered"
    elif qty_po > 0:
        ro_state, ro_status = "partial", "Partial Ordered"
    else:
        ro_state, ro_status = "active", "Open"

    if qty_po <= 0:
        po_state, po_status = "pending", "Belum dibuat"
    elif any(s == "Rejected" for s in po_statuses) and not any(s in ("Approved", "Partially Received", "Fully Received") for s in po_statuses):
        po_state, po_status = "error", "Rejected"
    elif any(s == "Waiting Approval" for s in po_statuses):
        po_state, po_status = "active", "Waiting Approval"
    elif qty_do >= qty_po and qty_po > 0:
        po_state, po_status = "done", "Fully Received"
    elif qty_do > 0:
        po_state, po_status = "partial", "Partially Received"
    else:
        po_state, po_status = "active", "Approved"

    if qty_do <= 0:
        do_state, do_status = "pending", "Belum diterima"
    elif qty_po > 0 and qty_do >= qty_po:
        do_state, do_status = "done", "Selesai diterima"
    else:
        do_state, do_status = "partial", "Partial"

    if qty_mi <= 0:
        mi_state, mi_status = "pending", "Belum dikeluarkan"
    elif qty_request > 0 and qty_mi >= qty_request:
        mi_state, mi_status = "done", "Completed"
    else:
        mi_state, mi_status = "partial", "Partial"

    outstanding = max(0, qty_request - qty_mi)
    stages = [
        {"key": "mro", "label": "MRO", "state": mro_state, "status": mro_status, "qty": qty_request, "documents": mro_ref_docs},
        {"key": "ro", "label": "RO", "state": ro_state, "status": ro_status, "qty": qty_ro, "documents": docs_with_qty(ro_docs, ro_allocs)},
        {"key": "po", "label": "PO", "state": po_state, "status": po_status, "qty": qty_po, "documents": docs_with_qty(po_docs, po_allocs)},
        {"key": "do", "label": "DO", "state": do_state, "status": do_status, "qty": qty_do, "documents": docs_with_qty(do_docs, do_allocs)},
        {"key": "mi", "label": "MI", "state": mi_state, "status": mi_status, "qty": qty_mi, "documents": docs_with_qty(mi_docs, mi_allocs)},
    ]
    return {
        "current": {"type": entity, "id": doc_id, "no": current.get("no"), "status": current.get("status")},
        "direct": False,
        "summary": {"request": qty_request, "ro": qty_ro, "po": qty_po, "received": qty_do,
                    "mi": qty_mi, "outstanding": outstanding},
        "stages": stages,
    }


def install(server):
    @server.app.get("/api/lifecycle/{entity}/{doc_id}")
    async def lifecycle(entity: str, doc_id: str, user=Depends(server.current_user)):
        server.require(user, "view")
        return await build_lifecycle(server, entity, doc_id)
