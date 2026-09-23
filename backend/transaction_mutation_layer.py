"""Global guarded edit/delete for operational transactions.

Rules:
- a transaction can be edited/deleted only when it has no active downstream document;
- deleting/editing a stock-posting document reverses its active ledger entries first;
- editing an approved procurement document resets approval so it must be submitted again;
- source allocations are rebuilt while preserving auditability;
- audit logs are retained even when the transaction header is physically removed.
"""
from copy import deepcopy
from fastapi import Depends, HTTPException

import uom_layer


META = {
    "mro": {"head": "mro", "lines": "mro_lines", "fk": "mro_id", "label": "MRO", "stock": False},
    "ro": {"head": "ro", "lines": "ro_lines", "fk": "ro_id", "label": "RO", "stock": False},
    "po": {"head": "po", "lines": "po_lines", "fk": "po_id", "label": "PO", "stock": False},
    "do": {"head": "do", "lines": "do_lines", "fk": "do_id", "label": "DO", "stock": True},
    "mi": {"head": "mi", "lines": "mi_lines", "fk": "mi_id", "label": "MI", "stock": True},
    "transfer": {"head": "transfers", "lines": "transfer_lines", "fk": "transfer_id", "label": "Transfer", "stock": True},
    "loan": {"head": "loans", "lines": "loan_lines", "fk": "loan_id", "label": "Loan", "stock": True},
    "adjustment": {"head": "adjustments", "lines": "adjustment_lines", "fk": "adjustment_id", "label": "Adjustment", "stock": True},
    "opname": {"head": "opname", "lines": "opname_lines", "fk": "opname_id", "label": "Opname", "stock": True},
}

TARGET_HEAD = {"ro": "ro", "po": "po", "do": "do", "mi": "mi"}


def _norm(v):
    return str(v or "").strip().lower()


async def _active_target(server, alloc):
    target_type = alloc.get("target_type")
    coll = TARGET_HEAD.get(target_type)
    if not coll:
        return True
    d = await getattr(server.db, coll).find_one({"id": alloc.get("target_doc_id")}, {"_id": 0})
    if not d:
        return False
    if d.get("cancelled") is True or d.get("deleted") is True:
        return False
    if _norm(d.get("status")) in ("cancelled", "canceled", "rejected"):
        return False
    if _norm(d.get("approval_status")) == "rejected":
        return False
    return True


async def _blockers(server, module, did):
    blockers = []
    allocs = await server.db.allocations.find({"source_doc_id": did}, {"_id": 0}).to_list(5000)
    seen = set()
    for a in allocs:
        if not await _active_target(server, a):
            continue
        key = (a.get("target_type"), a.get("target_doc_id"))
        if key in seen:
            continue
        seen.add(key)
        coll = TARGET_HEAD.get(a.get("target_type"))
        child = await getattr(server.db, coll).find_one({"id": a.get("target_doc_id")}, {"_id": 0}) if coll else None
        blockers.append({
            "type": str(a.get("target_type") or "").upper(),
            "id": a.get("target_doc_id"),
            "no": (child or {}).get("no") or a.get("target_doc_id"),
        })
    if module == "loan":
        returns = await server.db.loan_returns.find({"loan_id": did}, {"_id": 0}).to_list(1000)
        for r in returns:
            blockers.append({"type": "RETURN", "id": r.get("id"), "no": r.get("no") or r.get("id")})
    return blockers


async def _capability(server, module, did, user):
    if module not in META:
        raise HTTPException(404, "Modul transaksi tidak dikenal")
    meta = META[module]
    doc = await getattr(server.db, meta["head"]).find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"{meta['label']} tidak ditemukan")
    blockers = await _blockers(server, module, did)
    reason = None
    if blockers:
        names = ", ".join(f"{b['type']} {b['no']}" for b in blockers[:4])
        reason = f"Transaksi sudah digunakan oleh {names}. Hapus transaksi tersebut terlebih dahulu."
    return {
        "module": module,
        "id": did,
        "no": doc.get("no"),
        "can_edit": server.has_perm(user, "edit") and not blockers,
        "can_delete": server.has_perm(user, "delete") and not blockers,
        "blockers": blockers,
        "reason": reason,
    }


async def _reverse_ledgers(server, did, user, reason="edit"):
    rows = await server.db.stock_ledger.find({
        "doc_id": did,
        "is_reversal": {"$ne": True},
        "reversed": {"$ne": True},
    }, {"_id": 0}).sort("at", 1).to_list(10000)
    for row in rows:
        qty_in = float(row.get("qty_out") or 0)
        qty_out = float(row.get("qty_in") or 0)
        item_id = row.get("item_id")
        wh = row.get("warehouse_id")
        bal = await server.stock_balance(item_id, wh)
        running = bal + qty_in - qty_out
        await server.db.stock_ledger.insert_one({
            "id": server.gid(),
            "doc_type": f"Reversal {row.get('doc_type') or ''}".strip(),
            "doc_no": row.get("doc_no"),
            "doc_id": did,
            "item_id": item_id,
            "warehouse_id": wh,
            "qty_in": qty_in,
            "qty_out": qty_out,
            "running_balance": running,
            "project_id": row.get("project_id"),
            "unit_id": row.get("unit_id"),
            "division_id": row.get("division_id"),
            "user": user.get("email"),
            "at": server.now_iso(),
            "is_reversal": True,
            "reversal_of_ledger_id": row.get("id"),
            "reversal_reason": reason,
        })
        await server.db.item_warehouse.update_one(
            {"item_id": item_id, "warehouse_id": wh},
            {"$set": {"item_id": item_id, "warehouse_id": wh, "current_stock": running}},
            upsert=True,
        )
        await server.db.stock_ledger.update_one({"id": row.get("id")}, {"$set": {"reversed": True, "reversed_at": server.now_iso()}})


async def _incoming_for_old_line(server, line_id):
    return await server.db.allocations.find({"target_line_id": line_id}, {"_id": 0}).sort("at", 1).to_list(500)


async def _source_specs(server, module, raw_line, base_qty):
    explicit = raw_line.get("sources")
    if explicit:
        out = []
        for s in explicit:
            source_type = {"ro": "mro", "po": "ro", "do": "po", "mi": "mro"}.get(module)
            source_line_id = s.get("line_id") or s.get(f"{source_type}_line_id") or raw_line.get(f"{source_type}_line_id")
            source_doc_id = s.get(f"{source_type}_id") or raw_line.get(f"{source_type}_id")
            q = float(s.get("base_qty") if s.get("base_qty") is not None else s.get("qty") or 0)
            if source_line_id and source_doc_id and q > 0:
                out.append((source_type, source_line_id, source_doc_id, q))
        return out

    old_id = raw_line.get("id") or raw_line.get("_original_line_id")
    if not old_id:
        return []
    old = await _incoming_for_old_line(server, old_id)
    if not old:
        return []
    remaining = float(base_qty or 0)
    total_old = sum(float(a.get("qty") or 0) for a in old)
    if remaining > total_old + 1e-6:
        raise HTTPException(400, "Qty hasil edit melebihi qty sumber lama. Tarik ulang sumber transaksi terlebih dahulu.")
    out = []
    for a in old:
        if remaining <= 1e-9:
            break
        q = min(float(a.get("qty") or 0), remaining)
        if q > 0:
            out.append((a.get("source_type"), a.get("source_line_id"), a.get("source_doc_id"), q))
            remaining -= q
    return out


async def _allocated_elsewhere(server, source_line_id, target_type, current_did):
    rows = await server.db.allocations.find({"source_line_id": source_line_id, "target_type": target_type}, {"_id": 0}).to_list(5000)
    total = 0.0
    for a in rows:
        if a.get("target_doc_id") == current_did:
            continue
        if await _active_target(server, a):
            total += float(a.get("qty") or 0)
    return total


async def _validate_sources(server, module, did, specs, item_id):
    if module not in ("ro", "po", "do", "mi"):
        return
    source_coll = {"ro": "mro_lines", "po": "ro_lines", "do": "po_lines", "mi": "mro_lines"}[module]
    target_type = module
    for source_type, source_line_id, source_doc_id, qty in specs:
        row = await getattr(server.db, source_coll).find_one({"id": source_line_id}, {"_id": 0})
        if not row:
            raise HTTPException(400, "Sumber transaksi tidak ditemukan")
        if row.get("item_id") != item_id:
            raise HTTPException(400, "Barang berbeda dengan sumber transaksi")
        elsewhere = await _allocated_elsewhere(server, source_line_id, target_type, did)
        available = float(row.get("qty") or 0) - elsewhere
        if qty > available + 1e-6:
            raise HTTPException(400, "Qty hasil edit melebihi outstanding sumber transaksi")


async def _reset_approval(server, module, did):
    if module in ("mro", "ro"):
        await getattr(server.db, module).update_one({"id": did}, {"$set": {
            "submitted": False, "approval_status": None, "approval_mode": None,
        }})
    elif module == "po":
        await server.db.po.update_one({"id": did}, {"$set": {
            "status": "Draft", "approval_status": None, "approval_mode": None,
        }})
    await server.db.approval_tasks.delete_many({"module": module, "document_id": did})
    if module == "po":
        await server.db.po_approvals.delete_many({"po_id": did})


async def _refresh_po_status(server, po_id):
    if not po_id:
        return
    po = await server.db.po.find_one({"id": po_id}, {"_id": 0})
    if not po or po.get("cancelled"):
        return
    lines = await server.db.po_lines.find({"po_id": po_id}, {"_id": 0}).to_list(5000)
    total = sum(float(x.get("qty") or 0) for x in lines)
    received = 0.0
    for line in lines:
        rows = await server.db.allocations.find({"source_line_id": line.get("id"), "target_type": "do"}, {"_id": 0}).to_list(5000)
        for a in rows:
            if await _active_target(server, a):
                received += float(a.get("qty") or 0)
    if received <= 1e-9:
        status = "Approved" if po.get("approval_status") in ("Approved", "Not Required", "Legacy Approved") or po.get("status") != "Draft" else "Draft"
    elif total > 0 and received >= total - 1e-9:
        status = "Fully Received"
    else:
        status = "Partially Received"
    await server.db.po.update_one({"id": po_id}, {"$set": {"status": status}})


async def _normalize_qty_body(server, module, body):
    if module in ("mro", "ro", "po", "do", "mi", "transfer", "loan"):
        normalized, metas = await uom_layer._normalize_body(server, deepcopy(body or {}))
        return normalized, metas
    return deepcopy(body or {}), []


async def _replace(server, module, did, body, user):
    meta = META[module]
    head_col = getattr(server.db, meta["head"])
    line_col = getattr(server.db, meta["lines"])
    doc = await head_col.find_one({"id": did}, {"_id": 0})
    old_lines = await line_col.find({meta["fk"]: did}, {"_id": 0}).to_list(10000)
    old_line_by_id = {x.get("id"): x for x in old_lines}
    normalized, uom_metas = await _normalize_qty_body(server, module, body)
    raw_lines = normalized.get("lines") or []

    prepared = []
    for idx, line in enumerate(raw_lines):
        line = dict(line)
        if line.get("qty") is not None and float(line.get("qty") or 0) <= 0 and module not in ("adjustment", "opname"):
            continue
        specs = await _source_specs(server, module, line, line.get("qty"))
        await _validate_sources(server, module, did, specs, line.get("item_id"))
        prepared.append((line, specs, uom_metas[idx] if idx < len(uom_metas) else None))

    # Validate outbound stock using the balance that will exist after reversing this document.
    reversal_by_key = {}
    if meta["stock"]:
        ledgers = await server.db.stock_ledger.find({"doc_id": did, "is_reversal": {"$ne": True}, "reversed": {"$ne": True}}, {"_id": 0}).to_list(10000)
        for lg in ledgers:
            key = (lg.get("item_id"), lg.get("warehouse_id"))
            reversal_by_key[key] = reversal_by_key.get(key, 0.0) + float(lg.get("qty_out") or 0) - float(lg.get("qty_in") or 0)

        required_out = {}
        if module == "mi":
            for line, _, _ in prepared:
                wh = line.get("warehouse_id") or normalized.get("default_warehouse_id")
                required_out[(line.get("item_id"), wh)] = required_out.get((line.get("item_id"), wh), 0.0) + float(line.get("qty") or 0)
        elif module in ("transfer", "loan"):
            frm = normalized.get("from_warehouse_id")
            for line, _, _ in prepared:
                required_out[(line.get("item_id"), frm)] = required_out.get((line.get("item_id"), frm), 0.0) + float(line.get("qty") or 0)
        for key, qty in required_out.items():
            available = float(await server.stock_balance(*key) or 0) + reversal_by_key.get(key, 0.0)
            if qty > available + 1e-6 and not server.has_perm(user, "override_qty"):
                raise HTTPException(400, f"Stok tidak cukup setelah koreksi (tersedia {available})")

    old_po_ids = set()
    if module == "do":
        old_po_ids = {x.get("po_id") for x in old_lines if x.get("po_id")}

    if meta["stock"]:
        await _reverse_ledgers(server, did, user, "edit")

    await server.db.allocations.delete_many({"target_doc_id": did})
    await line_col.delete_many({meta["fk"]: did})

    # Header fields intentionally explicit so id/no/audit metadata cannot be overwritten.
    header_fields = {
        "mro": ("date","need_date","division_id","requester","department","default_warehouse_id","default_project_id","default_unit_id","spk","notes"),
        "ro": ("date","need_date","division_id","requester","department","default_warehouse_id","default_project_id","default_unit_id","spk","notes"),
        "po": ("date","supplier_id","division_id","payment_term","currency","supplier_bank_id","default_tax_id","eta","default_warehouse_id","default_project_id","default_unit_id","spk","tax_inclusive","supplier_notes","internal_notes"),
        "do": ("date","supplier_id","supplier_dn","supplier_invoice","invoice_date","default_warehouse_id","default_project_id","default_unit_id","spk","receiver","notes"),
        "mi": ("date","division_id","default_warehouse_id","default_project_id","default_unit_id","spk","receiver","department","source_type","notes"),
        "transfer": ("date","from_warehouse_id","to_warehouse_id","project_id","notes"),
        "loan": ("date","from_warehouse_id","to_warehouse_id","due_date","project_id","requester","notes"),
        "adjustment": ("date","warehouse_id","division_id","project_id","adj_type","reason","notes"),
        "opname": ("date","warehouse_id","division_id","mode","scope","notes"),
    }[module]
    patch = {k: normalized.get(k) for k in header_fields if k in normalized}
    patch["updated_by"] = user.get("email")
    patch["updated_at"] = server.now_iso()
    await head_col.update_one({"id": did}, {"$set": patch})

    if module in ("mro", "ro", "po"):
        await _reset_approval(server, module, did)

    new_lines = []
    for line, specs, umeta in prepared:
        lid = server.gid()
        if module == "mro":
            rec = {"id": lid, "mro_id": did, "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "unit": line.get("unit"), "warehouse_id": line.get("warehouse_id") or normalized.get("default_warehouse_id"), "project_id": line.get("project_id") or normalized.get("default_project_id"), "unit_id": line.get("unit_id") or normalized.get("default_unit_id"), "notes": line.get("notes")}
        elif module == "ro":
            rec = {"id": lid, "ro_id": did, "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "unit": line.get("unit"), "warehouse_id": line.get("warehouse_id") or normalized.get("default_warehouse_id"), "project_id": line.get("project_id") or normalized.get("default_project_id"), "unit_id": line.get("unit_id") or normalized.get("default_unit_id"), "notes": line.get("notes")}
        elif module == "po":
            rec = {"id": lid, "po_id": did, "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "unit": line.get("unit"), "warehouse_id": line.get("warehouse_id") or normalized.get("default_warehouse_id"), "project_id": line.get("project_id") or normalized.get("default_project_id"), "unit_id": line.get("unit_id") or normalized.get("default_unit_id"), "spk": normalized.get("spk"), "price": float(line.get("price") or 0), "discount": float(line.get("discount") or 0), "tax": float(line.get("tax") or 0), "tax_id": line.get("tax_id"), "tax_name": line.get("tax_name"), "notes": line.get("notes")}
        elif module == "do":
            rec = {"id": lid, "do_id": did, "po_id": (specs[0][2] if specs else line.get("po_id")), "po_line_id": (specs[0][1] if specs else line.get("po_line_id")), "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "unit": line.get("unit"), "warehouse_id": line.get("warehouse_id") or normalized.get("default_warehouse_id"), "project_id": line.get("project_id") or normalized.get("default_project_id"), "unit_id": line.get("unit_id") or normalized.get("default_unit_id"), "spk": normalized.get("spk"), "condition": line.get("condition", "Baik"), "notes": line.get("notes")}
        elif module == "mi":
            rec = {"id": lid, "mi_id": did, "mro_line_id": (specs[0][1] if specs else line.get("mro_line_id")), "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "unit": line.get("unit"), "warehouse_id": line.get("warehouse_id") or normalized.get("default_warehouse_id"), "project_id": line.get("project_id") or normalized.get("default_project_id"), "unit_id": line.get("unit_id") or normalized.get("default_unit_id"), "notes": line.get("notes")}
        elif module == "transfer":
            rec = {"id": lid, "transfer_id": did, "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "unit": line.get("unit"), "project_id": line.get("project_id"), "unit_id": line.get("unit_id"), "notes": line.get("notes")}
        elif module == "loan":
            rec = {"id": lid, "loan_id": did, "item_id": line.get("item_id"), "qty": float(line.get("qty") or 0), "returned": 0, "unit": line.get("unit"), "project_id": line.get("project_id"), "unit_id": line.get("unit_id"), "notes": line.get("notes")}
        elif module == "adjustment":
            wh = normalized.get("warehouse_id")
            before = await server.stock_balance(line.get("item_id"), wh)
            delta = float(line.get("adjustment") or 0)
            rec = {"id": lid, "adjustment_id": did, "item_id": line.get("item_id"), "before": before, "adjustment": delta, "after": before + delta, "reason": line.get("reason")}
        else:  # opname
            old = old_line_by_id.get(line.get("id")) or {}
            snapshot = float(line.get("snapshot") if line.get("snapshot") is not None else old.get("snapshot") or 0)
            rec = {"id": lid, "opname_id": did, "item_id": line.get("item_id") or old.get("item_id"), "snapshot": snapshot, "counted": line.get("counted")}
        if umeta:
            rec.update(umeta)
        await line_col.insert_one(rec)
        new_lines.append(rec)
        for source_type, source_line_id, source_doc_id, qty in specs:
            await server.create_alloc(source_type, source_line_id, source_doc_id, module, lid, did, qty, rec.get("item_id"))

    no = doc.get("no")
    if module == "po":
        inclusive = bool(normalized.get("tax_inclusive", False))
        grand = 0.0
        for rec in new_lines:
            gross = float(rec.get("qty") or 0) * float(rec.get("price") or 0)
            net = max(0.0, gross - float(rec.get("discount") or 0))
            rate = float(rec.get("tax") or 0)
            if inclusive and rate:
                dpp = net / (1 + rate / 100.0); tax_amount = net - dpp; total = net
            else:
                dpp = net; tax_amount = dpp * rate / 100.0; total = dpp + tax_amount
            await line_col.update_one({"id": rec["id"]}, {"$set": {"gross": gross, "dpp": dpp, "tax_amount": tax_amount, "total": total, "tax_inclusive": inclusive}})
            grand += total
        await head_col.update_one({"id": did}, {"$set": {"grand_total": grand, "status": "Draft"}})
    elif module == "do":
        await head_col.update_one({"id": did}, {"$set": {"status": "Posted"}})
        for rec in new_lines:
            await server.post_ledger("DO", no, did, rec["item_id"], rec["warehouse_id"], rec["qty"], 0, project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user)
    elif module == "mi":
        await head_col.update_one({"id": did}, {"$set": {"status": "Posted"}})
        for rec in new_lines:
            await server.post_ledger("MI", no, did, rec["item_id"], rec["warehouse_id"], 0, rec["qty"], project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), division_id=normalized.get("division_id"), user=user)
    elif module == "transfer":
        frm, to = normalized.get("from_warehouse_id"), normalized.get("to_warehouse_id")
        if frm == to:
            raise HTTPException(400, "Gudang asal dan tujuan sama")
        await head_col.update_one({"id": did}, {"$set": {"status": "Posted"}})
        for rec in new_lines:
            await server.post_ledger("Transfer Out", no, did, rec["item_id"], frm, 0, rec["qty"], project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user)
            await server.post_ledger("Transfer In", no, did, rec["item_id"], to, rec["qty"], 0, project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user)
    elif module == "loan":
        frm, to = normalized.get("from_warehouse_id"), normalized.get("to_warehouse_id")
        if frm == to:
            raise HTTPException(400, "Gudang pemberi dan peminjam sama")
        for rec in new_lines:
            await server.post_ledger("Loan Out", no, did, rec["item_id"], frm, 0, rec["qty"], user=user)
            await server.post_ledger("Loan In", no, did, rec["item_id"], to, rec["qty"], 0, user=user)
    elif module == "adjustment":
        wh = normalized.get("warehouse_id")
        for rec in new_lines:
            delta = float(rec.get("adjustment") or 0)
            await server.post_ledger("Stock Adjustment", no, did, rec["item_id"], wh, delta if delta > 0 else 0, -delta if delta < 0 else 0, division_id=normalized.get("division_id"), user=user)
    elif module == "opname":
        old_status = doc.get("status")
        if old_status == "Posted":
            wh = normalized.get("warehouse_id")
            for rec in new_lines:
                if rec.get("counted") is None:
                    continue
                variance = float(rec.get("counted") or 0) - float(rec.get("snapshot") or 0)
                if abs(variance) < 1e-9:
                    continue
                await server.post_ledger("Stock Opname Adjustment", no, did, rec["item_id"], wh, variance if variance > 0 else 0, -variance if variance < 0 else 0, user=user)
            await head_col.update_one({"id": did}, {"$set": {"status": "Posted", "posted_at": server.now_iso()}})

    if module == "do":
        new_po_ids = {rec.get("po_id") for rec in new_lines if rec.get("po_id")}
        for pid in old_po_ids | new_po_ids:
            await _refresh_po_status(server, pid)

    await server.audit(user, "edit", module, did, no, before={"header": doc, "lines": old_lines}, after={"header": normalized, "line_count": len(new_lines)})
    return {"ok": True, "id": did, "no": no, "approval_reset": module in ("mro", "ro", "po")}


async def _delete(server, module, did, user):
    meta = META[module]
    head_col = getattr(server.db, meta["head"])
    line_col = getattr(server.db, meta["lines"])
    doc = await head_col.find_one({"id": did}, {"_id": 0})
    lines = await line_col.find({meta["fk"]: did}, {"_id": 0}).to_list(10000)
    old_po_ids = {x.get("po_id") for x in lines if x.get("po_id")} if module == "do" else set()
    if meta["stock"]:
        await _reverse_ledgers(server, did, user, "delete")
    await server.db.allocations.delete_many({"$or": [{"target_doc_id": did}, {"source_doc_id": did}]})
    await line_col.delete_many({meta["fk"]: did})
    await server.db.approval_tasks.delete_many({"module": module, "document_id": did})
    if module == "po":
        await server.db.po_approvals.delete_many({"po_id": did})
    await server.db.attachments.update_many({"entity": module, "entity_id": did}, {"$set": {"is_deleted": True}})
    await head_col.delete_one({"id": did})
    for pid in old_po_ids:
        await _refresh_po_status(server, pid)
    await server.audit(user, "delete", module, did, doc.get("no"), before={"header": doc, "lines": lines})
    return {"ok": True, "id": did, "no": doc.get("no")}


def install(server):
    app = server.app

    @app.get("/api/transactions/{module}/{did}/capability", tags=["transaction-mutation"])
    async def transaction_capability(module: str, did: str, user=Depends(server.current_user)):
        return await _capability(server, module, did, user)

    @app.put("/api/transactions/{module}/{did}", tags=["transaction-mutation"])
    async def transaction_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        cap = await _capability(server, module, did, user)
        if cap["blockers"]:
            raise HTTPException(409, cap["reason"])
        return await _replace(server, module, did, body, user)

    @app.delete("/api/transactions/{module}/{did}", tags=["transaction-mutation"])
    async def transaction_delete(module: str, did: str, user=Depends(server.current_user)):
        server.require(user, "delete")
        cap = await _capability(server, module, did, user)
        if cap["blockers"]:
            raise HTTPException(409, cap["reason"])
        return await _delete(server, module, did, user)
