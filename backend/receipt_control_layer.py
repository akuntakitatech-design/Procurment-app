"""DO / PO receipt control (over receipt, closed PO, source lock, duplicate DN) and
transaction-list traceability enrichment (aggregated MRO/RO/PO/Project/Divisi/SPK + hover items).

Installed as the OUTERMOST wrapper of the DO create/edit/delete routes so every receipt is
validated against the latest PO receipt state under a single receipt lock.
"""
from __future__ import annotations

import asyncio
import math
from contextvars import ContextVar
from copy import deepcopy

from fastapi import Depends, HTTPException

EPS = 1e-6
CLOSED_MSG = "PO sudah selesai diterima dan telah ditutup. Silakan muat ulang data penerimaan."
OVER_OK: ContextVar = ContextVar("over_receipt_ok", default=frozenset())
_LOCK = asyncio.Lock()


def over_allowed(po_line_id) -> bool:
    return str(po_line_id) in OVER_OK.get()


def _norm(v):
    return str(v or "").strip().lower()


def _key(v):
    return " ".join(str(v or "").split()).upper()


def _is_active(d):
    if not d or d.get("cancelled") is True or d.get("deleted") is True:
        return False
    return _norm(d.get("status")) not in ("cancelled", "canceled", "rejected")


def _fmt(v):
    v = float(v or 0)
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.4f}".rstrip("0").rstrip(".")


def _find_route(app, path, method):
    for r in list(app.router.routes):
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set()):
            return r
    return None


def _uniq(values):
    return sorted({str(v).strip() for v in values if v not in (None, "") and str(v).strip()}, key=lambda s: s.lower())


# ------------------------------------------------------------------ receipt state
async def _received_map(server, po_line_ids):
    ids = [x for x in po_line_ids if x]
    if not ids:
        return {}, {}
    allocs = await server.db.allocations.find({"source_line_id": {"$in": ids}, "target_type": "do"}, {"_id": 0}).to_list(200000)
    do_ids = list({a.get("target_doc_id") for a in allocs if a.get("target_doc_id")})
    heads = {d["id"]: d for d in await server.db.do.find({"id": {"$in": do_ids}}, {"_id": 0}).to_list(200000)} if do_ids else {}
    rec, per = {}, {}
    for a in allocs:
        h = heads.get(a.get("target_doc_id"))
        if not _is_active(h):
            continue
        sid = a.get("source_line_id")
        rec[sid] = rec.get(sid, 0.0) + float(a.get("qty") or 0)
        per.setdefault(sid, []).append((a, h))
    return rec, per


def receipt_status(state):
    if sum(r for _, r in state) <= EPS:
        return "Belum Diterima"
    if any(q - r > EPS for q, r in state):
        return "Diterima Sebagian"
    if any(r - q > EPS for q, r in state):
        return "Over Receipt"
    return "Diterima Penuh"


def document_status(po, rs):
    st = po.get("status") or "Draft"
    if po.get("cancelled") is True or _norm(st) in ("cancelled", "canceled"):
        return "Cancelled"
    if _norm(st) == "rejected" or _norm(po.get("approval_status")) == "rejected":
        return "Rejected"
    if _norm(st) in ("draft", "waiting approval"):
        return st
    return "Closed" if rs in ("Diterima Penuh", "Over Receipt") else "Approved"


# ------------------------------------------------------------------ Status Dokumen PO (derived display)
# PO.status / receipt_status tetap state existing (dipakai source picker, approval, receipt control, dst).
# Untuk tampilan list/detail, tahap "Waiting Approval" dipecah sesuai posisi PO pada Approval 1 / Approval 2
# dari state aktual approval_tasks + po_approval2_batch(_items). Tidak disimpan ke DB.
DOC_WAITING_A1, DOC_READY_A2, DOC_WAITING_A2 = "Waiting Approval 1", "Ready Approval 2", "Waiting Approval 2"
A2_SUBMITTED_BATCH = ("diajukan", "selesai sebagian")


async def po_approval_stage_map(server, pos):
    """{po_id: stage} hanya untuk PO berstatus Waiting Approval. Batch-load (tanpa N+1).
    stage: Rejected | Waiting Approval 1 | Ready Approval 2 | Waiting Approval 2 | None (fallback legacy)."""
    ids = [p["id"] for p in pos or [] if p.get("id") and _norm(p.get("status")) == "waiting approval"
           and p.get("cancelled") is not True]
    if not ids:
        return {}
    db = server.db
    tasks = await db.approval_tasks.find({"module": "po", "document_id": {"$in": ids}}, {"_id": 0}).to_list(100000)
    by_po = {}
    for t in tasks:
        by_po.setdefault(t.get("document_id"), []).append(t)
    legacy_ids = [i for i in ids if i not in by_po]
    if legacy_ids:  # data lama: hanya mirror po_approvals
        for t in await db.po_approvals.find({"po_id": {"$in": legacy_ids}}, {"_id": 0}).to_list(100000):
            by_po.setdefault(t.get("po_id"), []).append(t)

    def current(ts):
        pend = [t for t in ts if _norm(t.get("status")) == "pending"]
        return min(pend, key=lambda t: int(t.get("seq") or 0)) if pend else None

    l2_ids = [c["id"] for ts in by_po.values() if (c := current(ts)) and int(c.get("seq") or 0) == 2 and c.get("id")]
    submitted = set()
    if l2_ids:
        items = await db.po_approval2_batch_items.find(
            {"approval_task_id": {"$in": l2_ids}, "status": "Pending"}, {"_id": 0}).to_list(100000)
        bids = list({i.get("batch_id") for i in items if i.get("batch_id")})
        batches = {b["id"]: b for b in await db.po_approval2_batches.find({"id": {"$in": bids}}, {"_id": 0}).to_list(100000)} if bids else {}
        submitted = {i.get("approval_task_id") for i in items
                     if _norm((batches.get(i.get("batch_id")) or {}).get("status")) in A2_SUBMITTED_BATCH}
    out = {}
    for pid in ids:
        ts = by_po.get(pid) or []
        if any(_norm(t.get("status")) == "rejected" for t in ts):
            out[pid] = "Rejected"
            continue
        c = current(ts)
        seq = int((c or {}).get("seq") or 0)
        out[pid] = (DOC_WAITING_A1 if seq == 1 else
                    (DOC_WAITING_A2 if c.get("id") in submitted else DOC_READY_A2) if seq == 2 else None)
    return out


def display_document_status(po, base, stage):
    """Status Dokumen tampilan. base = document_status() existing; stage dari po_approval_stage_map."""
    if _norm(base) == "draft":
        return "Draft"
    if _norm(base) == "waiting approval":
        return stage or "Waiting Approval"  # legacy tanpa task approval: fallback state PO existing
    return base


async def po_receipt_batch(server, pos):
    ids = [p["id"] for p in pos if p.get("id")]
    lines = await server.db.po_lines.find({"po_id": {"$in": ids}}, {"_id": 0}).to_list(500000) if ids else []
    rec, per = await _received_map(server, [l["id"] for l in lines])
    by_po = {}
    for l in lines:
        by_po.setdefault(l.get("po_id"), []).append(l)
    out = {}
    for p in pos:
        ls = by_po.get(p.get("id"), [])
        rs = receipt_status([(float(l.get("qty") or 0), rec.get(l["id"], 0.0)) for l in ls])
        out[p.get("id")] = {"receipt_status": rs, "document_status": document_status(p, rs), "lines": ls}
    return out, rec, per


async def refresh_po_receipt(server, po_id):
    po = await server.db.po.find_one({"id": po_id}, {"_id": 0}) if po_id else None
    if not po:
        return None
    batch, _, _ = await po_receipt_batch(server, [po])
    st = batch[po_id]
    await server.db.po.update_one({"id": po_id}, {"$set": {
        "receipt_status": st["receipt_status"], "document_status": st["document_status"],
        "receipt_closed": st["document_status"] == "Closed"}})
    return st


# ------------------------------------------------------------------ DO validation
def _line_source(line):
    src = ((line.get("sources") or [None])[0]) or {}
    return (line.get("po_id") or src.get("po_id"), line.get("po_line_id") or src.get("line_id") or src.get("po_line_id"))


async def _validate_receipt(server, body, current_do_id=None):
    import uom_layer
    import transaction_mutation_layer as Mutation
    payload = deepcopy(body or {})
    raw = payload.get("lines") or []
    for l in raw:
        try:
            q = float(l.get("qty") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Qty Terima tidak valid")
        if not math.isfinite(q):
            raise HTTPException(400, "Qty Terima tidak valid")
        if q < -EPS:
            raise HTTPException(400, "Qty Terima tidak boleh negatif")
    normalized, metas = await uom_layer._normalize_body(server, deepcopy(payload))
    nlines = normalized.get("lines") or []
    if not any(float(x.get("qty") or 0) > EPS for x in nlines):
        raise HTTPException(400, "Minimal satu item harus memiliki Qty Terima lebih dari 0")
    items = {}
    acc, info = {}, {}
    supplier_id = None
    for i, nl in enumerate(nlines):
        q = float(nl.get("qty") or 0)
        if q <= EPS:
            continue
        rl = raw[i] if i < len(raw) else nl
        po_id, pl_id = _line_source(nl)
        if not pl_id:
            continue
        pol = await server.db.po_lines.find_one({"id": pl_id}, {"_id": 0})
        if not pol:
            continue
        po = await server.db.po.find_one({"id": pol.get("po_id")}, {"_id": 0}) or {}
        supplier_id = supplier_id or po.get("supplier_id")
        if pol.get("item_id") not in items:
            items[pol.get("item_id")] = await server.db.items.find_one({"id": pol.get("item_id")}, {"_id": 0}) or {}
        code = items[pol.get("item_id")].get("code") or items[pol.get("item_id")].get("name") or "-"
        po_no = po.get("no") or "-"
        if str(nl.get("item_id")) != str(pol.get("item_id")):
            raise HTTPException(400, f"Barang penerimaan berbeda dengan barang pada PO {po_no}")
        for k, label in (("warehouse_id", "Gudang"), ("project_id", "Proyek"), ("unit_id", "Unit/Aset")):
            src, given = pol.get(k), rl.get(k)
            if src and given and str(src) != str(given):
                raise HTTPException(400, f"{label} item {code} terkunci mengikuti PO {po_no} dan tidak dapat diubah")
            if src:
                rl[k] = src
        src_notes, given_notes = str(pol.get("notes") or "").strip(), str(rl.get("notes") or "").strip()
        if src_notes and given_notes and given_notes != src_notes:
            raise HTTPException(400, f"Keterangan item {code} terkunci mengikuti PO {po_no}")
        if src_notes:
            rl["notes"] = pol.get("notes")
        if pol.get("uom_id") and rl.get("uom_id") and str(pol.get("uom_id")) != str(rl.get("uom_id")):
            raise HTTPException(400, f"Satuan item {code} harus mengikuti satuan PO {po_no}")
        meta = metas[i] if i < len(metas) else {}
        acc[pl_id] = acc.get(pl_id, 0.0) + q
        slot = info.setdefault(pl_id, {"pol": pol, "po": po, "code": code, "reason": "",
                                       "factor": float(pol.get("conversion_factor") or meta.get("conversion_factor") or 1) or 1.0,
                                       "unit": pol.get("display_unit") or pol.get("unit") or ""})
        r = str(rl.get("over_receipt_reason") or "").strip()
        if r and not slot["reason"]:
            slot["reason"] = r
    over = {}
    for pl_id, q in acc.items():
        s = info[pl_id]
        po_qty = float(s["pol"].get("qty") or 0)
        before = float(await Mutation._allocated_elsewhere(server, pl_id, "do", current_do_id) or 0)
        remaining = max(po_qty - before, 0.0)
        f = s["factor"]
        if remaining <= EPS:
            raise HTTPException(409, f"{CLOSED_MSG} (PO {s['po'].get('no') or '-'}, Item {s['code']})")
        ov = q - remaining
        if ov > EPS:
            if not s["reason"]:
                raise HTTPException(400, f"Qty Terima item {s['code']} melebihi sisa PO {s['po'].get('no') or '-'} "
                                         f"sebesar {_fmt(ov / f)} {s['unit']}. Alasan Penerimaan Berlebih wajib diisi.")
            over[pl_id] = {"po_id": s["pol"].get("po_id"), "po_no": s["po"].get("no"), "item_id": s["pol"].get("item_id"),
                           "qty_po": po_qty / f, "previous_received": before / f, "qty_received": q / f,
                           "over_qty": ov / f, "unit": s["unit"], "factor": f, "reason": s["reason"]}
    sid = payload.get("supplier_id") or supplier_id
    for field, label in (("supplier_dn", "No. Surat Jalan"), ("supplier_invoice", "No. Faktur")):
        v = _key(payload.get(field))
        if not v or not sid:
            continue
        for d in await server.db.do.find({"supplier_id": sid}, {"_id": 0}).to_list(100000):
            if d.get("id") != current_do_id and _is_active(d) and _key(d.get(field)) == v:
                raise HTTPException(409, f"{label} {payload.get(field)} dari supplier ini sudah tercatat pada {d.get('no')}. Penerimaan ganda diblokir.")
    return payload, over


async def _persist_over(server, did, over, user):
    await server.db.do_over_receipts.delete_many({"do_id": did})
    do = await server.db.do.find_one({"id": did}, {"_id": 0}) or {}
    lines = await server.db.do_lines.find({"do_id": did}, {"_id": 0}).to_list(5000)
    done = set()
    for l in lines:
        pl = l.get("po_line_id")
        o = over.get(pl) if pl not in done else None
        if o:
            done.add(pl)
        await server.db.do_lines.update_one({"id": l["id"]}, {"$set": {
            "over_receipt_qty": o["over_qty"] if o else 0, "over_receipt_reason": o["reason"] if o else None}})
    for pl, o in over.items():
        await server.db.do_over_receipts.insert_one({
            "id": server.gid(), "do_id": did, "do_no": do.get("no"), "do_date": do.get("date"), "po_line_id": pl,
            **{k: o[k] for k in ("po_id", "po_no", "item_id", "qty_po", "previous_received", "qty_received", "over_qty", "unit", "reason")},
            "user": user.get("email"), "user_name": user.get("name"), "posted_at": server.now_iso()})
        await server.audit(user, "over_receipt", "do", did, doc_no=do.get("no"),
                           reason=f"PO {o['po_no']}: Qty PO {_fmt(o['qty_po'])}, sebelumnya {_fmt(o['previous_received'])}, "
                                  f"terima {_fmt(o['qty_received'])}, berlebih {_fmt(o['over_qty'])} {o['unit']}. Alasan: {o['reason']}")


async def _do_po_ids(server, did):
    return {l.get("po_id") for l in await server.db.do_lines.find({"do_id": did}, {"_id": 0}).to_list(5000) if l.get("po_id")}


# ------------------------------------------------------------------ lineage / SPK helpers
async def _upstream(server, line_ids, source_type):
    ids = [x for x in line_ids if x]
    if not ids:
        return {}
    rows = await server.db.allocations.find({"target_line_id": {"$in": ids}, "source_type": source_type}, {"_id": 0}).to_list(500000)
    out = {}
    for a in rows:
        out.setdefault(a.get("target_line_id"), []).append(a)
    return out


async def _docs_no(server, coll, ids):
    ids = [x for x in set(ids) if x]
    if not ids:
        return {}
    return {d["id"]: d for d in await getattr(server.db, coll).find({"id": {"$in": ids}}, {"_id": 0}).to_list(500000)}


async def _spk_text(server, source_type, lines, uom_sym):
    ids = [l["id"] for l in lines if l.get("id")]
    if not ids:
        return {}
    rows = await server.db.procurement_item_spk_allocations.find({"source_type": source_type, "item_line_id": {"$in": ids}}, {"_id": 0}).to_list(500000)
    spk_ids = list({r.get("spk_id") for r in rows if r.get("spk_id")})
    spks = {s["id"]: s for s in await server.db.spk.find({"id": {"$in": spk_ids}}, {"_id": 0}).to_list(100000)} if spk_ids else {}
    by_line = {l["id"]: l for l in lines}
    out = {}
    for r in rows:
        l = by_line.get(r.get("item_line_id")) or {}
        f = float(l.get("conversion_factor") or 1) or 1.0
        num = (spks.get(r.get("spk_id")) or {}).get("spk_number") or "-"
        out.setdefault(r.get("item_line_id"), []).append((num, float(r.get("allocated_qty") or 0) / f, uom_sym(l)))
    return {k: sorted(v, key=lambda x: x[0]) for k, v in out.items()}


def _spk_join(entries):
    return ", ".join(f"{n}: {_fmt(q)} {u}".strip() for n, q, u in entries or [])


async def _lineage(server, module, lines):
    """Per line: {'mro': set(no), 'ro': set(no), 'po': set(no), 'mro_docs': set(id)}."""
    res = {l["id"]: {"mro": set(), "ro": set(), "po": set(), "mro_docs": set(), "ro_docs": set()} for l in lines if l.get("id")}
    chain_po = chain_ro = chain_mro = {}
    if module == "do":
        chain_po = {l["id"]: [l.get("po_line_id")] for l in lines if l.get("po_line_id")}
        pos = await _docs_no(server, "po", [l.get("po_id") for l in lines])
        for l in lines:
            if l.get("po_id") in pos:
                res[l["id"]]["po"].add(pos[l["po_id"]].get("no"))
    if module in ("do", "po"):
        po_line_ids = [x for v in chain_po.values() for x in v] if module == "do" else [l["id"] for l in lines]
        up = await _upstream(server, po_line_ids, "ro")
        ros = await _docs_no(server, "ro", [a.get("source_doc_id") for v in up.values() for a in v])
        chain_ro = {}
        for l in lines:
            pls = chain_po.get(l["id"], []) if module == "do" else [l["id"]]
            for pl in pls:
                for a in up.get(pl, []):
                    chain_ro.setdefault(l["id"], []).append(a.get("source_line_id"))
                    if a.get("source_doc_id") in ros:
                        res[l["id"]]["ro"].add(ros[a["source_doc_id"]].get("no"))
                        res[l["id"]]["ro_docs"].add(a["source_doc_id"])
    if module in ("do", "po", "ro", "mi"):
        if module == "ro" or module == "mi":
            chain_ro = {l["id"]: [l["id"]] for l in lines}
        up = await _upstream(server, [x for v in chain_ro.values() for x in v], "mro")
        mros = await _docs_no(server, "mro", [a.get("source_doc_id") for v in up.values() for a in v])
        for l in lines:
            for rl in chain_ro.get(l["id"], []):
                for a in up.get(rl, []):
                    if a.get("source_doc_id") in mros:
                        res[l["id"]]["mro"].add(mros[a["source_doc_id"]].get("no"))
                        res[l["id"]]["mro_docs"].add(a["source_doc_id"])
        res["_mros"] = mros
    return res


# ------------------------------------------------------------------ list traceability
LIST_CFG = {
    "mro": ("/api/mro", "mro_lines", "mro_id"),
    "ro": ("/api/ro", "ro_lines", "ro_id"),
    "po": ("/api/po", "po_lines", "po_id"),
    "do": ("/api/do", "do_lines", "do_id"),
    "mi": ("/api/mi", "mi_lines", "mi_id"),
    "transfer": ("/api/transfers", "transfer_lines", "transfer_id"),
    "loan": ("/api/loans", "loan_lines", "loan_id"),
    "adjustment": ("/api/adjustments", "adjustment_lines", "adjustment_id"),
    "opname": ("/api/opname", "opname_lines", "opname_id"),
}


async def enrich_list(server, module, rows):
    import doc_procurement
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
    if not rows:
        return rows
    _, coll, fk = LIST_CFG[module]
    m = await doc_procurement.maps()
    ids = [r["id"] for r in rows]
    lines = await getattr(server.db, coll).find({fk: {"$in": ids}}, {"_id": 0}).to_list(500000)
    by_doc = {}
    for l in lines:
        by_doc.setdefault(l.get(fk), []).append(l)

    def sym(l):
        u = m["uoms"].get(l.get("uom_id")) or {}
        if module in ("adjustment", "opname") or not l.get("uom_id"):
            it = m["items"].get(l.get("item_id")) or {}
            bu = m["uoms"].get(it.get("base_uom_id")) or {}
            return l.get("display_unit") or bu.get("symbol") or bu.get("name") or it.get("unit") or l.get("unit") or ""
        return l.get("display_unit") or u.get("symbol") or u.get("name") or l.get("unit") or ""

    async def _none():
        return {}
    spk, lin = await asyncio.gather(  # independen -> paralel
        _spk_text(server, module, lines, sym) if module in ("mro", "ro", "po", "do", "mi") else _none(),
        _lineage(server, module, lines) if module in ("ro", "po", "do", "mi") else _none())
    mros = lin.pop("_mros", {}) if lin else {}
    nm = lambda coll_, i: (m[coll_].get(i) or {}).get("name") if i else None
    for r in rows:
        ls = by_doc.get(r["id"], [])
        hdiv = r.get("division_name") or nm("divisions", r.get("division_id"))
        hproj = r.get("default_project_id") or r.get("project_id")
        mro_s, ro_s, po_s, proj_s, div_s, spk_s, wh_s, unit_s, req_s = (set() for _ in range(9))
        div_ids = {r["division_id"]} if r.get("division_id") else set()
        if hdiv:
            div_s.add(hdiv)
        items = []
        for l in ls:
            f = float(l.get("conversion_factor") or 1) or 1.0
            lg = lin.get(l.get("id")) or {}
            mro_s |= lg.get("mro", set()); ro_s |= lg.get("ro", set()); po_s |= lg.get("po", set())
            for mid in lg.get("mro_docs", set()):
                md = mros.get(mid) or {}
                if md.get("requester"):
                    req_s.add(md["requester"])
                if module in ("po", "do", "mi", "ro") and md.get("division_id"):
                    div_ids.add(md["division_id"])
                if module in ("po", "do", "mi", "ro") and nm("divisions", md.get("division_id")):
                    div_s.add(nm("divisions", md.get("division_id")))
            pname = nm("projects", l.get("project_id") or hproj)
            if pname:
                proj_s.add(pname)
            if nm("warehouses", l.get("warehouse_id")):
                wh_s.add(nm("warehouses", l.get("warehouse_id")))
            if l.get("unit_id") and m["units"].get(l["unit_id"]):
                un = m["units"][l["unit_id"]]
                unit_s.add(un.get("plate_no") or un.get("name"))
            sp = spk.get(l.get("id"))
            for n, _, _ in sp or []:
                spk_s.add(n)
            it = m["items"].get(l.get("item_id")) or {}
            desc = l.get("notes") or ""
            if module == "adjustment":
                qty = float(l.get("adjustment") or 0)
            elif module == "opname":
                c = l.get("counted")
                qty = (float(c) - float(l.get("snapshot") or 0)) if c is not None else None
                desc = f"Sistem {_fmt(l.get('snapshot'))} / Fisik {'-' if c is None else _fmt(c)}"
            else:
                qty = float(l.get("qty") or 0) / f
            items.append({"item": " — ".join(x for x in (it.get("code"), it.get("name")) if x) or "-", "desc": desc,
                          "qty": qty, "unit": sym(l), "project": pname or "-", "division": hdiv or "-",
                          "spk": _spk_join(sp) or "-"})
        for k in ("from_name", "to_name", "warehouse_name"):
            if r.get(k):
                wh_s.add(r[k])
        if module == "mro" and r.get("requester"):
            req_s.add(r["requester"])
        r["trace_mro"] = ", ".join(_uniq(mro_s))
        r["trace_ro"] = ", ".join(_uniq(ro_s))
        r["trace_po"] = ", ".join(_uniq(po_s))
        r["trace_project"] = ", ".join(_uniq(proj_s))
        r["trace_division"] = ", ".join(_uniq(div_s))
        r["trace_division_ids"] = sorted(div_ids)
        r["trace_spk"] = ", ".join(_uniq(spk_s))
        r["trace_warehouse"] = ", ".join(_uniq(wh_s))
        r["trace_unit"] = ", ".join(_uniq(unit_s))
        r["trace_requester"] = ", ".join(_uniq(req_s))
        r["items"] = items[:300]
        r["items_search"] = " ".join(f"{x['item']} {x['desc']}" for x in items[:300])
    if module == "po":
        batch, _, _ = await po_receipt_batch(server, rows)
        stages = await po_approval_stage_map(server, rows)
        for r in rows:
            st = batch.get(r["id"]) or {}
            r["receipt_status"] = st.get("receipt_status")
            r["document_status"] = display_document_status(r, st.get("document_status"), stages.get(r["id"]))
    return rows


# ------------------------------------------------------------------ detail decoration
async def decorate_po_detail(server, d):
    if not isinstance(d, dict) or not d.get("id"):
        return d
    batch, rec, per = await po_receipt_batch(server, [d])
    st = batch[d["id"]]
    stages = await po_approval_stage_map(server, [d])
    d["receipt_status"] = st["receipt_status"]
    d["document_status"] = display_document_status(d, st["document_status"], stages.get(d["id"]))
    overs = await server.db.do_over_receipts.find({"po_id": d["id"]}, {"_id": 0}).to_list(10000)
    over_by = {(o.get("do_id"), o.get("po_line_id")): o for o in overs}
    history = []
    for l in d.get("lines") or []:
        f = float(l.get("conversion_factor") or 1) or 1.0
        q, r = float(l.get("qty") or 0), rec.get(l.get("id"), 0.0)
        l["receipt"] = {"qty_po": q / f, "received": r / f, "remaining": max(q - r, 0) / f, "over": max(r - q, 0) / f,
                        "status": receipt_status([(q, r)])}
        for a, h in per.get(l.get("id"), []):
            o = over_by.get((h.get("id"), l.get("id"))) or {}
            history.append({"do_no": h.get("no"), "do_id": h.get("id"), "date": h.get("date"),
                            "item": l.get("item_name") or l.get("item_code"), "qty": float(a.get("qty") or 0) / f,
                            "unit": l.get("display_unit") or l.get("unit"), "over_qty": o.get("over_qty") or 0,
                            "reason": o.get("reason"), "user": o.get("user_name") or o.get("user")})
    d["receipt_history"] = sorted(history, key=lambda x: (str(x.get("date") or ""), str(x.get("do_no") or "")))
    return d


async def decorate_do_detail(server, d):
    if not isinstance(d, dict) or not d.get("lines"):
        return d
    import doc_procurement
    m = await doc_procurement.maps()
    lines = d["lines"]
    lin = await _lineage(server, "do", lines)
    lin.pop("_mros", None)
    pol_ids = [l.get("po_line_id") for l in lines if l.get("po_line_id")]
    pols = await server.db.po_lines.find({"id": {"$in": pol_ids}}, {"_id": 0}).to_list(10000) if pol_ids else []
    sym = lambda l: l.get("display_unit") or (m["uoms"].get(l.get("uom_id")) or {}).get("symbol") or l.get("unit") or ""
    po_spk = await _spk_text(server, "po", pols, sym)
    for l in lines:
        lg = lin.get(l.get("id")) or {}
        l["lineage"] = {"mro": ", ".join(_uniq(lg.get("mro", set()))), "ro": ", ".join(_uniq(lg.get("ro", set()))),
                        "po": l.get("po_no") or ", ".join(_uniq(lg.get("po", set()))),
                        "spk": _spk_join(po_spk.get(l.get("po_line_id")))}
    return d


async def enrich_pull_rows(server, rows):
    rows = list(rows or [])
    if not rows:
        return rows
    pos = await _docs_no(server, "po", [r.get("po_id") for r in rows])
    batch, _, _ = await po_receipt_batch(server, list(pos.values()))
    import source_reservation_layer as _SR
    keep = await _SR.current_do_po_ids(server)  # Edit DO: "Closed" karena DO ini sendiri tidak menutup picker
    rows = [r for r in rows if (st := (batch.get(r.get("po_id")) or {}).get("document_status")) not in ("Closed", "Cancelled", "Rejected")
            or (st == "Closed" and r.get("po_id") in keep)]
    pol_ids = [r.get("line_id") for r in rows]
    pols = await server.db.po_lines.find({"id": {"$in": pol_ids}}, {"_id": 0}).to_list(100000) if pol_ids else []
    pol_by = {p["id"]: p for p in pols}
    fake = [{"id": p["id"], "po_line_id": p["id"], "po_id": p.get("po_id")} for p in pols]
    lin = await _lineage(server, "do", fake)
    lin.pop("_mros", None)
    sym = lambda l: l.get("display_unit") or l.get("unit") or ""
    spk = await _spk_text(server, "po", pols, sym)
    for r in rows:
        lg = lin.get(r.get("line_id")) or {}
        p = pol_by.get(r.get("line_id")) or {}
        r["mro_no"] = ", ".join(_uniq(lg.get("mro", set())))
        r["ro_no"] = ", ".join(_uniq(lg.get("ro", set())))
        r["spk_text"] = _spk_join(spk.get(r.get("line_id")))
        r["notes"] = p.get("notes") or ""
        r["receipt_status"] = (batch.get(r.get("po_id")) or {}).get("receipt_status")
    return rows


# ------------------------------------------------------------------ install
def install(server):
    app = server.app

    def wrap(path, method, factory):
        route = _find_route(app, path, method)
        if not route:
            return
        app.router.routes.remove(route)
        app.add_api_route(path, factory(route.endpoint), methods=[method], tags=["receipt-control"])

    def create_factory(orig):
        async def create_do(body: dict, user=Depends(server.current_user)):
            server.require(user, "create")
            async with _LOCK:
                payload, over = await _validate_receipt(server, body)
                tok = OVER_OK.set(frozenset(over.keys()))
                try:
                    result = await orig(body=payload, user=user)
                finally:
                    OVER_OK.reset(tok)
                did = result.get("id") if isinstance(result, dict) else None
                if did:
                    await _persist_over(server, did, over, user)
                    for pid in await _do_po_ids(server, did):
                        await refresh_po_receipt(server, pid)
                    result = await _reload_do(did, user, result)
            return result
        return create_do

    async def _reload_do(did, user, fallback):
        route = _find_route(app, "/api/do/{did}", "GET")
        try:
            return await route.endpoint(did=did, user=user) if route else fallback
        except HTTPException:
            return fallback

    def edit_factory(orig):
        async def transaction_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module not in ("do", "po"):
                return await orig(module=module, did=did, body=body, user=user)
            if module == "po":
                result = await orig(module=module, did=did, body=body, user=user)
                await refresh_po_receipt(server, did)
                return result
            async with _LOCK:
                old = await _do_po_ids(server, did)
                payload, over = await _validate_receipt(server, body, current_do_id=did)
                tok = OVER_OK.set(frozenset(over.keys()))
                try:
                    result = await orig(module=module, did=did, body=payload, user=user)
                finally:
                    OVER_OK.reset(tok)
                await _persist_over(server, did, over, user)
                for pid in old | await _do_po_ids(server, did):
                    await refresh_po_receipt(server, pid)
            return result
        return transaction_edit

    def delete_factory(orig):
        async def transaction_delete(module: str, did: str, user=Depends(server.current_user)):
            if module != "do":
                return await orig(module=module, did=did, user=user)
            async with _LOCK:
                old = await _do_po_ids(server, did)
                result = await orig(module=module, did=did, user=user)
                await server.db.do_over_receipts.delete_many({"do_id": did})
                for pid in old:
                    await refresh_po_receipt(server, pid)
            return result
        return transaction_delete

    wrap("/api/do", "POST", create_factory)
    wrap("/api/transactions/{module}/{did}", "PUT", edit_factory)
    wrap("/api/transactions/{module}/{did}", "DELETE", delete_factory)

    def po_detail_factory(orig):
        async def get_po(did: str, user=Depends(server.current_user)):
            return await decorate_po_detail(server, await orig(did=did, user=user))
        return get_po

    def do_detail_factory(orig):
        async def get_do(did: str, user=Depends(server.current_user)):
            return await decorate_do_detail(server, await orig(did=did, user=user))
        return get_do

    def pull_factory(orig):
        async def pull_po_for_do(supplier_id: str = None, user=Depends(server.current_user)):
            return await enrich_pull_rows(server, await orig(supplier_id=supplier_id, user=user))
        return pull_po_for_do

    wrap("/api/po/{did}", "GET", po_detail_factory)
    wrap("/api/do/{did}", "GET", do_detail_factory)
    wrap("/api/pull/po-for-do", "GET", pull_factory)

    for module, (path, _, _) in LIST_CFG.items():
        def list_factory(orig, module=module):
            async def list_docs(user=Depends(server.current_user)):
                return await enrich_list(server, module, await orig(user=user))
            list_docs.__name__ = f"list_{module}_traced"
            return list_docs
        wrap(path, "GET", list_factory)

    def email_factory(orig):
        async def send_po_email(did: str, body: dict, user=Depends(server.current_user)):
            po = await server.db.po.find_one({"id": did}, {"_id": 0}) or {}
            log = {"id": server.gid(), "po_id": did, "po_no": po.get("no"), "to": str((body or {}).get("to") or "").strip(),
                   "cc": (body or {}).get("cc") or "", "subject": (body or {}).get("subject"),
                   "user": user.get("email"), "user_name": user.get("name"), "sent_at": server.now_iso(),
                   "po_revision": po.get("updated_at") or po.get("created_at"), "po_status": po.get("status")}
            try:
                result = await orig(did=did, body=body, user=user)
            except HTTPException as e:
                await server.db.po_email_logs.insert_one({**log, "status": "failed", "error": str(e.detail)})
                raise
            except Exception as e:  # SMTP / infrastructure failure: never report fake success
                await server.db.po_email_logs.insert_one({**log, "status": "failed", "error": str(e)[:500]})
                raise HTTPException(502, f"Email gagal dikirim: {str(e)[:200]}")
            await server.db.po_email_logs.insert_one({**log, "status": "sent"})
            return result
        return send_po_email

    wrap("/api/po/{did}/email", "POST", email_factory)

    @app.get("/api/po/{did}/email-context", tags=["receipt-control"])
    async def po_email_context(did: str, user=Depends(server.current_user)):
        import email_outbound_layer as E
        server.require(user, "print")
        po = await server.db.po.find_one({"id": did}, {"_id": 0})
        if not po:
            raise HTTPException(404, "PO tidak ditemukan")
        sup = await server.db.suppliers.find_one({"id": po.get("supplier_id")}, {"_id": 0}) or {}
        contacts = sup.get("contacts") or []
        primary = next((c for c in contacts if c.get("is_primary")), contacts[0] if contacts else {})
        cfg = await E.public_config(server)
        logs = await server.db.po_email_logs.find({"po_id": did}, {"_id": 0}).sort("sent_at", -1).to_list(20)
        return {"po_no": po.get("no"), "status": po.get("status"), "supplier_name": sup.get("name"),
                "default_to": sup.get("email") or (primary or {}).get("email") or "",
                "subject": f"Purchase Order {po.get('no') or ''}".strip(),
                "message": "Terlampir informasi Purchase Order yang telah disetujui.",
                "attachment_name": f"{str(po.get('no') or 'PO').replace('/', '-')}.html",
                "attachment_format": "HTML", "email_ready": bool(cfg.get("ready")), "logs": logs}
