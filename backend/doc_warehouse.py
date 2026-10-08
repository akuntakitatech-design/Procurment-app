"""Transfer, Loan, Return, Stock Adjustment, Stock Opname, Attachments."""
import uuid
from fastapi import Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import Response
from server import (api, db, gid, now_iso, clean, current_user, require, has_perm,
                    audit, notify, next_number, post_ledger, post_movement, stock_balance)
import storage as S
import server


async def _wh_map():
    return {w["id"]: w for w in await db.warehouses.find({}, {"_id": 0}).to_list(2000)}

async def _item_map():
    return {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)}


# ---------------- TRANSFER ----------------
# Multi gudang per item: HEADER = metadata + default; LINE = sumber posting (lihat transfer_lines.py).
import transfer_lines as TL


async def _named(coll, ids):
    ids = [x for x in set(ids) if x]
    if not ids:
        return {}
    rows = await getattr(db, coll).find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "code": 1, "plate_no": 1}).to_list(len(ids) + 5)
    return {r["id"]: r for r in rows}


def _summary(names):
    names = [n for n in names if n]
    if not names:
        return None
    return names[0] if len(names) == 1 else f"{names[0]} +{len(names) - 1}"


@api.get("/transfers")
async def list_transfers(user=Depends(current_user)):
    require(user, "view")
    docs = await db.transfers.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    wm = await _wh_map()
    ids = [d["id"] for d in docs]
    all_lines = await db.transfer_lines.find({"transfer_id": {"$in": ids}}, {"_id": 0, "transfer_id": 1, "from_warehouse_id": 1, "to_warehouse_id": 1}).to_list(500000) if ids else []
    by_doc = {}
    for l in all_lines:
        by_doc.setdefault(l.get("transfer_id"), []).append(l)
    for d in docs:
        ls = by_doc.get(d["id"], [])
        froms = list(dict.fromkeys(TL.line_from(l, d) for l in ls)) or [d.get("from_warehouse_id")]
        tos = list(dict.fromkeys(TL.line_to(l, d) for l in ls)) or [d.get("to_warehouse_id")]
        # Ringkasan dari LINE (bukan header default): "Gudang A" atau "Gudang A +1".
        d["from_name"] = _summary([wm.get(x, {}).get("name") for x in froms])
        d["to_name"] = _summary([wm.get(x, {}).get("name") for x in tos])
        d["multi_warehouse"] = len(froms) > 1 or len(tos) > 1
        d["line_count"] = len(ls)
    return docs


@api.get("/transfers/{did}")
async def get_transfer(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.transfers.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "Transfer tidak ditemukan")
    wm = await _wh_map(); im = await _item_map()
    lines = await db.transfer_lines.find({"transfer_id": did}, {"_id": 0}).to_list(500)
    pm = await _named("projects", [TL.line_project(l, d) for l in lines] + [d.get("project_id")])
    um = await _named("units", [TL.line_unit(l, d) for l in lines])
    d["legacy_header_warehouse"] = TL.is_legacy(d)
    for l in lines:
        it = im.get(l["item_id"], {}); l["item_code"] = it.get("code"); l["item_name"] = it.get("name")
        legacy = TL.is_legacy(d) and (not l.get("from_warehouse_id") or not l.get("to_warehouse_id"))
        # Transaksi LAMA: fallback header hanya saat dibaca (tidak disimpan ulang). Transaksi BARU: murni line.
        l["from_warehouse_id"] = TL.line_from(l, d); l["to_warehouse_id"] = TL.line_to(l, d)
        l["project_id"] = TL.line_project(l, d); l["unit_id"] = TL.line_unit(l, d)
        l["legacy_header_warehouse"] = legacy
        l["from_name"] = wm.get(l["from_warehouse_id"], {}).get("name")
        l["to_name"] = wm.get(l["to_warehouse_id"], {}).get("name")
        l["project_name"] = (pm.get(l.get("project_id")) or {}).get("name")
        u = um.get(l.get("unit_id")) or {}
        l["unit_name"] = u.get("plate_no") or u.get("name")
    d["lines"] = lines
    d["from_name"] = wm.get(d.get("from_warehouse_id"), {}).get("name")
    d["to_name"] = wm.get(d.get("to_warehouse_id"), {}).get("name")
    d["project_name"] = (pm.get(d.get("project_id")) or {}).get("name")
    d["division_name"] = (await _named("divisions", [d.get("division_id")])).get(d.get("division_id"), {}).get("name")
    return d


@api.post("/transfers")
async def create_transfer(body: dict, user=Depends(current_user)):
    require(user, "create")
    lines = [l for l in TL.resolve_lines(body) if float(l.get("qty", 0) or 0) > 0]
    im = await _item_map()
    # Hard-block SEBELUM ada penulisan: gudang per line, asal != tujuan, stok per (barang, gudang asal LINE).
    await TL.validate_lines(server, lines, user, item_names={k: v.get("name") for k, v in im.items()})
    draft_id = body.get("attachment_draft_id") or None
    did = gid()
    claimed = await TL.claim_draft(server, draft_id, user, did)  # 404/409 sebelum ada penulisan stok
    try:
        no = await next_number("TRF")
        await db.transfers.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
            # Header = default/snapshot dokumen; posting membaca gudang line.
            "from_warehouse_id": body.get("from_warehouse_id") or None, "to_warehouse_id": body.get("to_warehouse_id") or None,
            "project_id": body.get("project_id"), "division_id": body.get("division_id"),
            "warehouse_source": TL.WAREHOUSE_SOURCE_LINE, "line_warehouse_ids": TL.line_warehouse_ids(lines),
            "notes": body.get("notes"), "status": "Posted", "created_by": user.get("email"), "created_at": now_iso()})
        for l in lines:
            qty = float(l.get("qty", 0))
            lid = gid()
            rec = {"id": lid, "transfer_id": did, "item_id": l["item_id"], "qty": qty, "unit": l.get("unit"),
                   "from_warehouse_id": l["from_warehouse_id"], "to_warehouse_id": l["to_warehouse_id"],
                   "project_id": l.get("project_id"), "unit_id": l.get("unit_id"), "notes": l.get("notes")}
            await db.transfer_lines.insert_one(rec)
            out = await TL.post_line(server, no, did, rec, user, body.get("date"))
            await db.transfer_lines.update_one({"id": lid}, {"$set": {
                "cost_snapshot": out.get("unit_cost"), "transfer_value": float(out.get("value_out") or 0)}})
    except Exception:
        # Posting gagal: transaksi tidak terbentuk (movement direversal), draft lampiran tetap draft -> bisa retry.
        await TL.rollback_failed_post(server, did, user)
        if claimed:
            await TL.release_draft(server, draft_id, did)
        raise
    if claimed:
        await TL.bind_draft_attachments(server, draft_id, did, user)  # bind HANYA setelah posting sukses
    await audit(user, "create", "transfer", did, no)
    return await get_transfer(did, user)


# ---------------- ATTACHMENT DRAFT TRANSFER (upload sebelum posting) ----------------
@api.post("/attachment-drafts")
async def create_attachment_draft(body: dict, user=Depends(current_user)):
    if (body or {}).get("module") != TL.DRAFT_MODULE:
        raise HTTPException(400, "Modul draft lampiran tidak didukung")
    if not has_perm(user, "transfer.create"):
        raise HTTPException(403, "Anda tidak memiliki izin untuk menambah data")
    require(user, "upload_attachment")
    await TL.cleanup_expired_drafts(server)  # draft orphan > 24 jam milik tenant aktif
    # tenant_id/owner diambil dari konteks server (tenant proxy + user terautentikasi), bukan dari payload.
    doc = {"id": str(uuid.uuid4()), "module": TL.DRAFT_MODULE, "owner_id": user.get("id"), "owner_email": user.get("email"),
           "bound_to": None, "binding": False, "created_at": now_iso()}
    await db.attachment_drafts.insert_one(doc)
    return clean(doc)


@api.delete("/attachment-drafts/{draft_id}")
async def discard_attachment_draft(draft_id: str, user=Depends(current_user)):
    d = await TL.get_owned_draft(server, draft_id, user)
    if d.get("bound_to"):
        return {"ok": True, "bound_to": d["bound_to"]}  # sudah final: lampiran final tidak dihapus
    removed = await TL.purge_draft(db, d, S)
    return {"ok": True, "removed": removed}


# ---------------- LOAN ----------------
async def loan_line_state(l):
    returned = l.get("returned", 0)
    return {"qty": l.get("qty", 0), "returned": returned, "outstanding": max(0, l.get("qty", 0) - returned)}


@api.get("/loans")
async def list_loans(user=Depends(current_user)):
    require(user, "view")
    docs = await db.loans.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    wm = await _wh_map()
    for d in docs:
        lines = await db.loan_lines.find({"loan_id": d["id"]}, {"_id": 0}).to_list(500)
        outs = sum(max(0, l.get("qty", 0) - l.get("returned", 0)) for l in lines)
        d["outstanding_total"] = outs
        d["status"] = "Completed" if outs == 0 and lines else ("Partial Returned" if any(l.get("returned", 0) for l in lines) else "Open")
        d["from_name"] = wm.get(d.get("from_warehouse_id"), {}).get("name")
        d["to_name"] = wm.get(d.get("to_warehouse_id"), {}).get("name")
    return docs


@api.get("/loans/{did}")
async def get_loan(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.loans.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "Pinjaman tidak ditemukan")
    wm = await _wh_map(); im = await _item_map()
    lines = await db.loan_lines.find({"loan_id": did}, {"_id": 0}).to_list(500)
    outs = 0
    for l in lines:
        it = im.get(l["item_id"], {}); l["item_code"] = it.get("code"); l["item_name"] = it.get("name")
        l["outstanding"] = max(0, l.get("qty", 0) - l.get("returned", 0)); outs += l["outstanding"]
    d["lines"] = lines
    d["outstanding_total"] = outs
    d["status"] = "Completed" if outs == 0 and lines else ("Partial Returned" if any(l.get("returned", 0) for l in lines) else "Open")
    d["from_name"] = wm.get(d.get("from_warehouse_id"), {}).get("name")
    d["to_name"] = wm.get(d.get("to_warehouse_id"), {}).get("name")
    return d


@api.post("/loans")
async def create_loan(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid(); no = await next_number("LOAN")
    frm = body["from_warehouse_id"]; to = body["to_warehouse_id"]
    if frm == to: raise HTTPException(400, "Gudang pemberi dan peminjam sama")
    await db.loans.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "from_warehouse_id": frm, "to_warehouse_id": to, "due_date": body.get("due_date"),
        "division_id": body.get("division_id"),
        "project_id": body.get("project_id"), "requester": body.get("requester", user.get("name")),
        "notes": body.get("notes"), "created_by": user.get("email"), "created_at": now_iso()})
    for l in body.get("lines", []):
        qty = float(l.get("qty", 0))
        if qty <= 0: continue
        avail = await stock_balance(l["item_id"], frm)
        if qty > avail + 1e-6 and not has_perm(user, "override_qty"):
            raise HTTPException(400, f"Stok pemberi tidak cukup (tersedia {avail})")
        lid = gid()
        await db.loan_lines.insert_one({"id": lid, "loan_id": did, "item_id": l["item_id"],
            "qty": qty, "returned": 0, "unit": l.get("unit"), "project_id": l.get("project_id"),
            "unit_id": l.get("unit_id"), "notes": l.get("notes")})
        # OUT at source moving-average snapshot; store the loan cost so returns reuse it (no P/L).
        out = await post_movement("Loan Out", no, did, l["item_id"], frm, 0, qty, user=user,
                                  line_id=lid, source_key=f"LOAN-O::{lid}", txn_at=body.get("date"))
        lv = float(out.get("value_out") or 0); uc = out.get("unit_cost")
        await db.loan_lines.update_one({"id": lid}, {"$set": {"cost_snapshot": uc, "loan_value": lv}})
        # Borrowing warehouse physically receives the stock carrying the ORIGINAL loan value.
        await post_movement("Loan In", no, did, l["item_id"], to, qty, 0, user=user, value_in=lv,
                            line_id=lid, source_key=f"LOAN-I::{lid}", txn_at=body.get("date"), require_cost=True)
    await audit(user, "create", "loan", did, no)
    await notify("Pinjaman baru", f"{no} dibuat", "loan", None)
    return await get_loan(did, user)


@api.get("/loans/{did}/returnable")
async def loan_returnable(did: str, user=Depends(current_user)):
    im = await _item_map()
    lines = await db.loan_lines.find({"loan_id": did}, {"_id": 0}).to_list(500)
    out = []
    for l in lines:
        outstanding = max(0, l.get("qty", 0) - l.get("returned", 0))
        if outstanding > 0:
            it = im.get(l["item_id"], {})
            out.append({"loan_line_id": l["id"], "item_id": l["item_id"], "item_code": it.get("code"),
                "item_name": it.get("name"), "unit": l.get("unit"), "qty": l.get("qty", 0),
                "returned": l.get("returned", 0), "outstanding": outstanding})
    return out


@api.post("/loans/{did}/return")
async def return_loan(did: str, body: dict, user=Depends(current_user)):
    require(user, "create")
    loan = await db.loans.find_one({"id": did})
    if not loan: raise HTTPException(404, "Pinjaman tidak ditemukan")
    rid = gid(); no = await next_number("RET")
    await db.loan_returns.insert_one({"id": rid, "no": no, "loan_id": did, "date": body.get("date", now_iso()),
        "notes": body.get("notes"), "created_by": user.get("email"), "created_at": now_iso()})
    for l in body.get("lines", []):
        qty = float(l.get("qty", 0))
        if qty <= 0: continue
        ll = await db.loan_lines.find_one({"id": l["loan_line_id"]})
        if not ll: continue
        rem = ll.get("qty", 0) - ll.get("returned", 0)
        if qty > rem + 1e-6 and not has_perm(user, "override_qty"):
            raise HTTPException(400, "Qty return melebihi outstanding")
        await db.loan_lines.update_one({"id": ll["id"]}, {"$inc": {"returned": qty}})
        # Return reuses the ORIGINAL loan cost snapshot deterministically (no gain/loss from avg drift).
        uc = float(ll.get("cost_snapshot") or 0); rv = qty * uc
        await post_movement("Loan Return Out", no, rid, ll["item_id"], loan["to_warehouse_id"], 0, qty,
                            user=user, reversal_value=rv, line_id=ll["id"],
                            source_key=f"LOANRET-O::{rid}::{ll['id']}", txn_at=body.get("date"))
        await post_movement("Loan Return In", no, rid, ll["item_id"], loan["from_warehouse_id"], qty, 0,
                            user=user, value_in=rv, line_id=ll["id"],
                            source_key=f"LOANRET-I::{rid}::{ll['id']}", txn_at=body.get("date"), require_cost=True)
    await audit(user, "create", "loan_return", rid, no)
    return await get_loan(did, user)


# ---------------- STOCK ADJUSTMENT ----------------
async def _resolve_in_cost(item_id, wh, approved, reason):
    """Resolve the unit cost for a positive (IN) stock change under moving average.
    Case A (existing qty>0 and avg>0): default = current avg; override allowed only with a reason.
    Case B (qty 0 / no avg): approved unit cost mandatory (>0). Never defaults to 0 or latest PO.
    Returns (unit_cost, overridden)."""
    iw = await db.item_warehouse.find_one({"item_id": item_id, "warehouse_id": wh}) or {}
    cur_qty = float(iw.get("current_stock") or 0); cur_avg = float(iw.get("avg_cost") or 0)
    ap = None
    try:
        ap = float(approved) if approved not in (None, "") else None
    except Exception:
        ap = None
    if cur_qty > 0 and cur_avg > 0:
        if ap is None:
            return cur_avg, False
        if ap <= 0:
            raise HTTPException(400, "Approved Unit Cost tidak valid (harus > 0)")
        if abs(ap - cur_avg) > 1e-6 and not (reason and str(reason).strip()):
            raise HTTPException(400, "Alasan wajib diisi karena Approved Unit Cost berbeda dari rata-rata persediaan saat ini.")
        return ap, abs(ap - cur_avg) > 1e-6
    if ap is None or ap <= 0:
        raise HTTPException(400, "Approved Unit Cost wajib diisi (tidak ada rata-rata persediaan untuk item/gudang ini).")
    return ap, True


@api.get("/adjustments")
async def list_adjustments(user=Depends(current_user)):
    require(user, "view")
    docs = await db.adjustments.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    wm = await _wh_map()
    for d in docs:
        d["warehouse_name"] = wm.get(d.get("warehouse_id"), {}).get("name")
        d["line_count"] = await db.adjustment_lines.count_documents({"adjustment_id": d["id"]})
    return docs


@api.get("/adjustments/{did}")
async def get_adjustment(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.adjustments.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "Adjustment tidak ditemukan")
    wm = await _wh_map(); im = await _item_map()
    lines = await db.adjustment_lines.find({"adjustment_id": did}, {"_id": 0}).to_list(500)
    for l in lines:
        it = im.get(l["item_id"], {}); l["item_code"] = it.get("code"); l["item_name"] = it.get("name")
    d["lines"] = lines
    d["warehouse_name"] = wm.get(d.get("warehouse_id"), {}).get("name")
    return d


@api.post("/adjustments")
async def create_adjustment(body: dict, user=Depends(current_user)):
    require(user, "stock_adjustment")
    did = gid(); no = await next_number("ADJ")
    wh = body["warehouse_id"]
    await db.adjustments.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "warehouse_id": wh, "division_id": body.get("division_id"), "project_id": body.get("project_id"),
        "adj_type": body.get("adj_type", "Koreksi"), "reason": body.get("reason"), "notes": body.get("notes"),
        "status": "Posted", "created_by": user.get("email"), "created_at": now_iso()})
    for l in body.get("lines", []):
        before = await stock_balance(l["item_id"], wh)
        delta = float(l.get("adjustment", 0))
        if abs(delta) < 1e-9: continue
        after = before + delta
        lid = gid()
        unit_cost = None; overridden = False
        if delta > 0:
            unit_cost, overridden = await _resolve_in_cost(l["item_id"], wh, l.get("approved_unit_cost"), l.get("reason"))
        await db.adjustment_lines.insert_one({"id": lid, "adjustment_id": did, "item_id": l["item_id"],
            "before": before, "adjustment": delta, "after": after, "reason": l.get("reason"),
            "approved_unit_cost": unit_cost, "cost_overridden": overridden})
        qty_in = delta if delta > 0 else 0
        qty_out = -delta if delta < 0 else 0
        await post_movement("Stock Adjustment", no, did, l["item_id"], wh, qty_in, qty_out,
                            division_id=body.get("division_id"), user=user, line_id=lid,
                            unit_cost_in=(unit_cost if delta > 0 else None), require_cost=(delta > 0),
                            source_key=f"ADJ::{lid}", txn_at=body.get("date"))
        if delta > 0 and overridden:
            await audit(user, "override_cost", "adjustment", did, no, reason=l.get("reason"),
                        after={"item_id": l["item_id"], "approved_unit_cost": unit_cost})
    await audit(user, "create", "adjustment", did, no, reason=body.get("reason"))
    return await get_adjustment(did, user)


# ---------------- STOCK OPNAME ----------------
@api.get("/opname")
async def list_opname(user=Depends(current_user)):
    require(user, "view")
    docs = await db.opname.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    wm = await _wh_map()
    for d in docs:
        d["warehouse_name"] = wm.get(d.get("warehouse_id"), {}).get("name")
        d["line_count"] = await db.opname_lines.count_documents({"opname_id": d["id"]})
    return docs


@api.get("/opname/{did}")
async def get_opname(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.opname.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "Stock Opname tidak ditemukan")
    wm = await _wh_map(); im = await _item_map()
    lines = await db.opname_lines.find({"opname_id": did}, {"_id": 0}).to_list(2000)
    for l in lines:
        it = im.get(l["item_id"], {}); l["item_code"] = it.get("code"); l["item_name"] = it.get("name"); l["unit"] = it.get("unit")
        l["variance"] = (l.get("counted") if l.get("counted") is not None else l.get("snapshot", 0)) - l.get("snapshot", 0)
    d["lines"] = lines
    d["warehouse_name"] = wm.get(d.get("warehouse_id"), {}).get("name")
    return d


@api.post("/opname")
async def create_opname(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid(); no = await next_number("OPN")
    wh = body["warehouse_id"]
    await db.opname.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "warehouse_id": wh, "division_id": body.get("division_id"), "mode": body.get("mode", "live"),
        "scope": body.get("scope", "all"), "notes": body.get("notes"), "status": "Counting",
        "created_by": user.get("email"), "created_at": now_iso()})
    # snapshot
    iws = await db.item_warehouse.find({"warehouse_id": wh}, {"_id": 0}).to_list(5000)
    im = await _item_map()
    for iw in iws:
        it = im.get(iw["item_id"], {})
        if body.get("scope") == "division" and body.get("division_id") and it.get("division_id") != body["division_id"]:
            continue
        await db.opname_lines.insert_one({"id": gid(), "opname_id": did, "item_id": iw["item_id"],
            "snapshot": iw.get("current_stock", 0), "counted": None})
    await audit(user, "create", "opname", did, no)
    return await get_opname(did, user)


@api.put("/opname/{did}/count")
async def opname_count(did: str, body: dict, user=Depends(current_user)):
    require(user, "edit")
    for l in body.get("lines", []):
        patch = {"counted": float(l["counted"])} if l.get("counted") is not None else {}
        if l.get("approved_unit_cost") is not None:
            patch["approved_unit_cost"] = l.get("approved_unit_cost")
        if l.get("reason") is not None:
            patch["reason"] = l.get("reason")
        if patch:
            await db.opname_lines.update_one({"id": l["line_id"]}, {"$set": patch})
    await db.opname.update_one({"id": did}, {"$set": {"status": body.get("status", "Review")}})
    await audit(user, "edit", "opname", did)
    return await get_opname(did, user)


@api.post("/opname/{did}/submit")
async def opname_submit(did: str, user=Depends(current_user)):
    require(user, "submit")
    await db.opname.update_one({"id": did}, {"$set": {"status": "Waiting Approval"}})
    return await get_opname(did, user)


@api.post("/opname/{did}/post")
async def opname_post(did: str, user=Depends(current_user)):
    require(user, "post_stock_opname")
    d = await db.opname.find_one({"id": did})
    if not d: raise HTTPException(404, "Opname tidak ditemukan")
    if d.get("status") == "Posted": raise HTTPException(400, "Sudah diposting")
    wh = d["warehouse_id"]
    lines = await db.opname_lines.find({"opname_id": did}, {"_id": 0}).to_list(5000)
    for l in lines:
        if l.get("counted") is None: continue
        variance = l["counted"] - l.get("snapshot", 0)
        if abs(variance) < 1e-9: continue
        lid = l.get("id")
        if variance > 0:
            # surplus = inventory IN; needs a valid valuation basis. Approved cost + reason are
            # captured earlier on the line via PUT /opname/{id}/count (stored on opname_lines).
            unit_cost, overridden = await _resolve_in_cost(l["item_id"], wh, l.get("approved_unit_cost"), l.get("reason"))
            await post_movement("Stock Opname Adjustment", d["no"], did, l["item_id"], wh, variance, 0,
                                user=user, line_id=lid, unit_cost_in=unit_cost, require_cost=True,
                                source_key=f"OPN::{did}::{lid}", txn_at=d.get("date"))
            if overridden:
                await audit(user, "override_cost", "opname", did, d.get("no"), reason=l.get("reason"),
                            after={"item_id": l["item_id"], "approved_unit_cost": unit_cost})
        else:
            # shortage = inventory OUT at current average snapshot
            await post_movement("Stock Opname Adjustment", d["no"], did, l["item_id"], wh, 0, -variance,
                                user=user, line_id=lid, source_key=f"OPN::{did}::{lid}", txn_at=d.get("date"))
    await db.opname.update_one({"id": did}, {"$set": {"status": "Posted", "approved_by": user.get("name"), "posted_at": now_iso()}})
    await audit(user, "approve", "opname", did, d.get("no"))
    return await get_opname(did, user)


# ---------------- ATTACHMENTS ----------------
@api.post("/attachments")
async def upload_attachment(request: Request, file: UploadFile = File(...),
                            entity: str = Form(...), entity_id: str = Form(...),
                            category: str = Form("Lainnya"), note: str = Form("")):
    user = await current_user(request)
    require(user, "upload_attachment")
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "bin"
    path = f"{S.APP_NAME}/uploads/{entity}/{gid()}.{ext}"
    data = await file.read()
    ct = file.content_type or S.MIME_TYPES.get(ext, "application/octet-stream")
    result = S.put_object(path, data, ct)
    doc = {"id": gid(), "storage_path": result["path"], "original_filename": file.filename,
           "content_type": ct, "size": result.get("size", len(data)), "entity": entity,
           "entity_id": entity_id, "category": category, "note": note,
           "uploaded_by": user.get("name"), "is_deleted": False, "created_at": now_iso()}
    await db.attachments.insert_one(doc)
    await audit(user, "upload_file", entity, entity_id, after={"file": file.filename})
    return clean(doc)


@api.get("/attachments")
async def list_attachments(entity: str, entity_id: str, user=Depends(current_user)):
    return await db.attachments.find({"entity": entity, "entity_id": entity_id, "is_deleted": False}, {"_id": 0}).to_list(200)


@api.get("/attachments/{aid}/download")
async def download_attachment(aid: str, request: Request, auth: str = Query(None)):
    if auth:
        await S.init_storage()
        from auth import get_current_user
        try:
            await get_current_user(request, db)
        except Exception:
            pass
    rec = await db.attachments.find_one({"id": aid, "is_deleted": False})
    if not rec: raise HTTPException(404, "File tidak ditemukan")
    data, ct = S.get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct),
                    headers={"Content-Disposition": f'inline; filename="{rec["original_filename"]}"'})


@api.delete("/attachments/{aid}")
async def delete_attachment(aid: str, user=Depends(current_user)):
    require(user, "delete")
    await db.attachments.update_one({"id": aid}, {"$set": {"is_deleted": True}})
    return {"ok": True}
