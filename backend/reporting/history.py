"""Rekonstruksi posisi Procurement per tanggal cut-off (historis) — read-only, dari bukti bertanggal.

Dipakai bila tanggal akhir filter < hari ini, agar kartu "Posisi s/d" (dan drill-down rf_asof) menggambarkan
keadaan PADA cut-off, bukan status saat ini:
  - Approval : approval_tasks (atau po_approvals legacy) -> tahap pertama yang BELUM disetujui pada cut-off
               (acted_at WIB <= cut-off). Ditolak <= cut-off -> Rejected. Tahap 2 'Menunggu Approval 2' bila
               masuk batch Approval 2 yang diajukan (submitted_at) <= cut-off, selain itu 'Siap Diajukan Approval 2'.
  - Receipt  : qty diterima = alokasi PO->DO dengan DO aktif bertanggal <= cut-off.
  - MRO/RO   : sisa = qty - alokasi ke dokumen target (RO/MI/PO) bertanggal <= cut-off.
PO tanpa jejak approval (data lama / auto-approve) mempertahankan state approval existing (tidak dikarang).
Draft / Cancelled tidak direkonstruksi (tanggal batal tidak tercatat) — mengikuti state existing.
"""
from __future__ import annotations

import receipt_control_layer as RC

from . import scope as S

FULL = ("Diterima Penuh", "Over Receipt")
_PO_STATUS = {"Belum Diterima": "Approved", "Diterima Sebagian": "Partially Received"}


def _n(v):
    return str(v or "").strip().lower()


async def _received_as_of(server, line_ids, cutoff):
    ids = [x for x in line_ids if x]
    if not ids:
        return {}
    allocs = await server.db.allocations.find({"source_line_id": {"$in": ids}, "target_type": "do"},
                                              {"_id": 0, "source_line_id": 1, "target_doc_id": 1, "qty": 1}).to_list(None)
    do_ids = list({a.get("target_doc_id") for a in allocs if a.get("target_doc_id")})
    heads = {d["id"]: d for d in await server.db.do.find({"id": {"$in": do_ids}}, {"_id": 0, "id": 1, "date": 1, "status": 1,
                                                                                  "cancelled": 1, "deleted": 1}).to_list(None)} if do_ids else {}
    rec = {}
    for a in allocs:
        h = heads.get(a.get("target_doc_id"))
        if not RC._is_active(h) or str(h.get("date") or "")[:10] > cutoff:
            continue
        rec[a["source_line_id"]] = rec.get(a["source_line_id"], 0.0) + float(a.get("qty") or 0)
    return rec


async def _approval_tasks(server, ids):
    tasks = await server.db.approval_tasks.find({"module": "po", "document_id": {"$in": ids}}, {"_id": 0}).to_list(None)
    by_po = {}
    for t in tasks:
        by_po.setdefault(t.get("document_id"), []).append(t)
    legacy = [i for i in ids if i not in by_po]
    if legacy:
        for t in await server.db.po_approvals.find({"po_id": {"$in": legacy}}, {"_id": 0}).to_list(None):
            by_po.setdefault(t.get("po_id"), []).append(t)
    return by_po


async def _a2_submitted(server, task_ids, cutoff):
    """approval_task_id yang pada cut-off sudah masuk batch Approval 2 berstatus diajukan."""
    if not task_ids:
        return set()
    items = await server.db.po_approval2_batch_items.find({"approval_task_id": {"$in": list(task_ids)}}, {"_id": 0}).to_list(None)
    bids = list({i.get("batch_id") for i in items if i.get("batch_id")})
    batches = {b["id"]: b for b in await server.db.po_approval2_batches.find({"id": {"$in": bids}}, {"_id": 0}).to_list(None)} if bids else {}
    out = set()
    for i in items:
        b = batches.get(i.get("batch_id")) or {}
        sub = S.local_day(b.get("submitted_at"))
        if sub and sub <= cutoff:
            out.add(i.get("approval_task_id"))
    return out


def _approved_by(t, cutoff):
    return _n(t.get("status")) == "approved" and S.local_day(t.get("acted_at")) <= cutoff


async def po_rows_as_of(server, rows, cutoff):
    """Baris PO (sudah ter-enrich) -> salinan dengan document_status / receipt_status / status PADA cut-off."""
    rows = [r for r in rows if r.get("id")]
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    lines = await server.db.po_lines.find({"po_id": {"$in": ids}}, {"_id": 0, "id": 1, "po_id": 1, "qty": 1}).to_list(None)
    rec = await _received_as_of(server, [ln["id"] for ln in lines if ln.get("id")], cutoff)
    by_po_lines = {}
    for ln in lines:
        by_po_lines.setdefault(ln.get("po_id"), []).append(ln)
    tasks = await _approval_tasks(server, ids)
    pend2 = set()
    stage = {}
    for pid, ts in tasks.items():
        if any(_n(t.get("status")) == "rejected" and S.local_day(t.get("acted_at")) <= cutoff for t in ts):
            stage[pid] = ("Rejected", None)
            continue
        pend = sorted([t for t in ts if not _approved_by(t, cutoff)], key=lambda t: int(t.get("seq") or 0))
        if pend:
            stage[pid] = ("pending", pend[0])
            if int(pend[0].get("seq") or 0) == 2 and pend[0].get("id"):
                pend2.add(pend[0]["id"])
        else:
            stage[pid] = ("approved", None)
    submitted = await _a2_submitted(server, pend2, cutoff)
    out = []
    for r in rows:
        cur = r.get("document_status")
        rs = RC.receipt_status([(float(ln.get("qty") or 0), rec.get(ln.get("id"), 0.0)) for ln in by_po_lines.get(r["id"], [])])
        x = {**r, "receipt_status": rs, "as_of": cutoff}
        if cur in ("Draft", "Cancelled") or r.get("cancelled") is True:
            out.append(x)
            continue
        st = stage.get(r["id"])
        if st is None:  # tanpa jejak approval: state approval existing; tahap penerimaan per cut-off
            if cur in ("Approved", "Closed"):
                x["document_status"] = "Closed" if rs in FULL else "Approved"
                x["status"] = _PO_STATUS.get(rs, "Fully Received")
        elif st[0] == "Rejected":
            x["document_status"], x["status"] = "Rejected", "Rejected"
        elif st[0] == "pending":
            seq = int(st[1].get("seq") or 0)
            x["status"] = "Waiting Approval"
            x["document_status"] = RC.DOC_WAITING_A1 if seq <= 1 else (
                RC.DOC_WAITING_A2 if st[1].get("id") in submitted else RC.DOC_READY_A2)
        else:
            x["document_status"] = "Closed" if rs in FULL else "Approved"
            x["status"] = _PO_STATUS.get(rs, "Fully Received")
        out.append(x)
    return out


async def outstanding_doc_ids_as_of(server, module, ids, cutoff):
    """MRO/RO yang masih bersisa PADA cut-off: alokasi hanya dari dokumen target bertanggal <= cut-off."""
    if not ids:
        return set()
    coll, fk, targets = ("mro_lines", "mro_id", ["ro", "mi"]) if module == "mro" else ("ro_lines", "ro_id", ["po"])
    lines = await getattr(server.db, coll).find({fk: {"$in": list(ids)}}, {"_id": 0, "id": 1, fk: 1, "qty": 1}).to_list(None)
    lids = [ln["id"] for ln in lines if ln.get("id")]
    allocs = await server.db.allocations.find({"source_line_id": {"$in": lids}, "target_type": {"$in": targets}},
                                              {"_id": 0, "source_line_id": 1, "qty": 1, "target_type": 1, "target_doc_id": 1,
                                               "at": 1}).to_list(None) if lids else []
    days = {}
    for t in targets:
        tids = list({a.get("target_doc_id") for a in allocs if a.get("target_type") == t and a.get("target_doc_id")})
        if tids:
            for d in await getattr(server.db, t).find({"id": {"$in": tids}}, {"_id": 0, "id": 1, "date": 1}).to_list(None):
                days[(t, d["id"])] = str(d.get("date") or "")[:10]
    used = {}
    for a in allocs:
        day = days.get((a.get("target_type"), a.get("target_doc_id"))) or S.local_day(a.get("at"))
        if day and day <= cutoff:
            used[a["source_line_id"]] = used.get(a["source_line_id"], 0.0) + float(a.get("qty") or 0)
    return {ln[fk] for ln in lines if float(ln.get("qty") or 0) - used.get(ln.get("id"), 0.0) > 1e-9}
