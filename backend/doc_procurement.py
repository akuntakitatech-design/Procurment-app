"""MRO, RO, PO, DO, MI + PO approval workflow."""
from fastapi import Depends, HTTPException
from server import (api, db, gid, now_iso, clean, current_user, require, has_perm,
                    is_global, audit, notify, next_number, alloc_out, create_alloc,
                    post_ledger, stock_balance)


async def maps():
    return {
        "items": {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)},
        "warehouses": {w["id"]: w for w in await db.warehouses.find({}, {"_id": 0}).to_list(2000)},
        "projects": {p["id"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(2000)},
        "units": {u["id"]: u for u in await db.units.find({}, {"_id": 0}).to_list(2000)},
        "divisions": {d["id"]: d for d in await db.divisions.find({}, {"_id": 0}).to_list(500)},
        "suppliers": {s["id"]: s for s in await db.suppliers.find({}, {"_id": 0}).to_list(2000)},
    }


def enrich_line(l, m):
    it = m["items"].get(l.get("item_id"), {})
    l["item_code"] = it.get("code"); l["item_name"] = it.get("name")
    if not l.get("unit"):
        l["unit"] = it.get("unit")
    l["warehouse_name"] = m["warehouses"].get(l.get("warehouse_id"), {}).get("name")
    l["project_name"] = m["projects"].get(l.get("project_id"), {}).get("name")
    l["unit_name"] = m["units"].get(l.get("unit_id"), {}).get("name")
    return l


# ---------------- MRO ----------------
async def mro_line_monitor(line):
    lid = line["id"]; qty = line.get("qty", 0)
    qty_ro = await alloc_out(lid, "ro")
    qty_mi = await alloc_out(lid, "mi")
    ro_allocs = await db.allocations.find({"source_line_id": lid, "target_type": "ro"}, {"_id": 0}).to_list(500)
    qty_po = 0; qty_received = 0
    for a in ro_allocs:
        rl = a["target_line_id"]; portion = a["qty"]
        po_of_ro = await alloc_out(rl, "po")
        qty_po += min(portion, po_of_ro)
        po_allocs = await db.allocations.find({"source_line_id": rl, "target_type": "po"}, {"_id": 0}).to_list(500)
        rec = 0
        for pa in po_allocs:
            rec += await alloc_out(pa["target_line_id"], "do")
        qty_received += min(portion, rec)
    return {"qty_request": qty, "qty_ro": qty_ro, "qty_po": qty_po,
            "qty_received": qty_received, "qty_mi": qty_mi, "outstanding": max(0, qty - qty_mi)}


def mro_status(lines_mon, cancelled=False, submitted=True):
    if cancelled:
        return "Cancelled"
    if not submitted:
        return "Draft"
    total_req = sum(l["qty_request"] for l in lines_mon)
    total_mi = sum(l["qty_mi"] for l in lines_mon)
    if total_req > 0 and total_mi >= total_req:
        return "Completed"
    if total_mi > 0:
        return "Partial"
    return "Open"


@api.get("/mro")
async def list_mro(user=Depends(current_user)):
    require(user, "view")
    docs = await db.mro.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    m = await maps()
    for d in docs:
        lines = await db.mro_lines.find({"mro_id": d["id"]}, {"_id": 0}).to_list(500)
        mon = [await mro_line_monitor(l) for l in lines]
        d["status"] = mro_status(mon, d.get("cancelled"), d.get("submitted", True))
        d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
        d["line_count"] = len(lines)
        d["outstanding_total"] = sum(x["outstanding"] for x in mon)
    return docs


@api.get("/mro/{did}")
async def get_mro(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.mro.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(404, "MRO tidak ditemukan")
    m = await maps()
    lines = await db.mro_lines.find({"mro_id": did}, {"_id": 0}).to_list(500)
    mon = []
    for l in lines:
        enrich_line(l, m)
        l["monitor"] = await mro_line_monitor(l)
        mon.append(l["monitor"])
    d["lines"] = lines
    d["status"] = mro_status(mon, d.get("cancelled"), d.get("submitted", True))
    d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
    return d


@api.post("/mro")
async def create_mro(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid()
    no = await next_number("MRO")
    header = {"id": did, "no": no, "date": body.get("date", now_iso()),
              "need_date": body.get("need_date"), "division_id": body.get("division_id"),
              "requester": body.get("requester", user.get("name")), "department": body.get("department"),
              "default_warehouse_id": body.get("default_warehouse_id"),
              "default_project_id": body.get("default_project_id"), "notes": body.get("notes"),
              "submitted": body.get("submitted", False), "cancelled": False,
              "created_by": user.get("email"), "created_at": now_iso()}
    await db.mro.insert_one(header)
    for l in body.get("lines", []):
        await db.mro_lines.insert_one({"id": gid(), "mro_id": did, "item_id": l["item_id"],
            "qty": float(l.get("qty", 0)), "unit": l.get("unit"),
            "warehouse_id": l.get("warehouse_id") or header["default_warehouse_id"],
            "project_id": l.get("project_id") or header["default_project_id"],
            "unit_id": l.get("unit_id"), "notes": l.get("notes")})
    await audit(user, "create", "mro", did, no)
    await notify("MRO baru", f"{no} dibuat", "mro", header["division_id"])
    return await get_mro(did, user)


@api.put("/mro/{did}")
async def update_mro(did: str, body: dict, user=Depends(current_user)):
    require(user, "edit")
    d = await db.mro.find_one({"id": did})
    if not d:
        raise HTTPException(404, "MRO tidak ditemukan")
    if d.get("submitted") and not has_perm(user, "override_qty"):
        raise HTTPException(400, "MRO sudah submit, tidak bisa diedit langsung")
    upd = {k: body[k] for k in ("date","need_date","division_id","requester","department",
           "default_warehouse_id","default_project_id","notes") if k in body}
    await db.mro.update_one({"id": did}, {"$set": upd})
    if "lines" in body:
        await db.mro_lines.delete_many({"mro_id": did})
        for l in body["lines"]:
            await db.mro_lines.insert_one({"id": gid(), "mro_id": did, "item_id": l["item_id"],
                "qty": float(l.get("qty", 0)), "unit": l.get("unit"),
                "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"),
                "unit_id": l.get("unit_id"), "notes": l.get("notes")})
    await audit(user, "edit", "mro", did, d.get("no"))
    return await get_mro(did, user)


@api.post("/mro/{did}/submit")
async def submit_mro(did: str, user=Depends(current_user)):
    require(user, "submit")
    await db.mro.update_one({"id": did}, {"$set": {"submitted": True}})
    await audit(user, "submit", "mro", did)
    return await get_mro(did, user)


@api.post("/mro/{did}/cancel")
async def cancel_mro(did: str, body: dict = None, user=Depends(current_user)):
    require(user, "cancel")
    await db.mro.update_one({"id": did}, {"$set": {"cancelled": True}})
    await audit(user, "cancel", "mro", did, reason=(body or {}).get("reason"))
    return {"ok": True}


# ---- pull sources ----
@api.get("/pull/mro-for-ro")
async def pull_mro_for_ro(user=Depends(current_user)):
    m = await maps()
    out = []
    mros = await db.mro.find({"submitted": True, "cancelled": {"$ne": True}}, {"_id": 0}).to_list(1000)
    for d in mros:
        for l in await db.mro_lines.find({"mro_id": d["id"]}, {"_id": 0}).to_list(500):
            processed = await alloc_out(l["id"], "ro")
            outstanding = l.get("qty", 0) - processed
            if outstanding > 0:
                enrich_line(l, m)
                out.append({"mro_id": d["id"], "mro_no": d["no"], "line_id": l["id"],
                    "item_id": l["item_id"], "item_code": l["item_code"], "item_name": l["item_name"],
                    "unit": l["unit"], "requested": l["qty"], "processed": processed, "outstanding": outstanding,
                    "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"),
                    "unit_id": l.get("unit_id"), "warehouse_name": l.get("warehouse_name"),
                    "project_name": l.get("project_name")})
    return out


@api.get("/pull/mro-for-mi")
async def pull_mro_for_mi(user=Depends(current_user)):
    m = await maps()
    out = []
    mros = await db.mro.find({"submitted": True, "cancelled": {"$ne": True}}, {"_id": 0}).to_list(1000)
    for d in mros:
        for l in await db.mro_lines.find({"mro_id": d["id"]}, {"_id": 0}).to_list(500):
            issued = await alloc_out(l["id"], "mi")
            outstanding = l.get("qty", 0) - issued
            if outstanding > 0:
                enrich_line(l, m)
                avail = await stock_balance(l["item_id"], l.get("warehouse_id"))
                out.append({"mro_id": d["id"], "mro_no": d["no"], "line_id": l["id"],
                    "item_id": l["item_id"], "item_code": l["item_code"], "item_name": l["item_name"],
                    "unit": l["unit"], "requested": l["qty"], "issued": issued, "outstanding": outstanding,
                    "available": avail, "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"),
                    "unit_id": l.get("unit_id"), "warehouse_name": l.get("warehouse_name"),
                    "project_name": l.get("project_name")})
    return out


# ---------------- RO ----------------
async def ro_line_state(line):
    ordered = await alloc_out(line["id"], "po")
    return {"qty": line.get("qty", 0), "ordered": ordered, "outstanding": max(0, line.get("qty", 0) - ordered)}


def ro_status(states, cancelled=False, submitted=True):
    if cancelled: return "Cancelled"
    if not submitted: return "Draft"
    tot = sum(s["qty"] for s in states); ordered = sum(s["ordered"] for s in states)
    if tot > 0 and ordered >= tot: return "Fully Ordered"
    if ordered > 0: return "Partial Ordered"
    return "Open"


@api.get("/ro")
async def list_ro(user=Depends(current_user)):
    require(user, "view")
    docs = await db.ro.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    m = await maps()
    for d in docs:
        lines = await db.ro_lines.find({"ro_id": d["id"]}, {"_id": 0}).to_list(500)
        states = [await ro_line_state(l) for l in lines]
        d["status"] = ro_status(states, d.get("cancelled"), d.get("submitted", True))
        d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
        d["line_count"] = len(lines)
    return docs


@api.get("/ro/{did}")
async def get_ro(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.ro.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "RO tidak ditemukan")
    m = await maps()
    lines = await db.ro_lines.find({"ro_id": did}, {"_id": 0}).to_list(500)
    states = []
    for l in lines:
        enrich_line(l, m)
        st = await ro_line_state(l); l.update({"ordered": st["ordered"], "outstanding": st["outstanding"]})
        # source MRO refs
        srcs = await db.allocations.find({"target_line_id": l["id"], "source_type": "mro"}, {"_id": 0}).to_list(50)
        refs = []
        for s in srcs:
            mh = await db.mro.find_one({"id": s["source_doc_id"]}, {"_id": 0})
            if mh: refs.append({"no": mh["no"], "id": mh["id"], "qty": s["qty"]})
        l["mro_refs"] = refs
        states.append(st)
    d["lines"] = lines
    d["status"] = ro_status(states, d.get("cancelled"), d.get("submitted", True))
    d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
    return d


@api.post("/ro")
async def create_ro(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid(); no = await next_number("RO")
    await db.ro.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "division_id": body.get("division_id"), "requester": body.get("requester", user.get("name")),
        "default_warehouse_id": body.get("default_warehouse_id"), "default_project_id": body.get("default_project_id"),
        "notes": body.get("notes"), "submitted": body.get("submitted", False), "cancelled": False,
        "created_by": user.get("email"), "created_at": now_iso()})
    for l in body.get("lines", []):
        lid = gid()
        await db.ro_lines.insert_one({"id": lid, "ro_id": did, "item_id": l["item_id"],
            "qty": float(l.get("qty", 0)), "unit": l.get("unit"), "warehouse_id": l.get("warehouse_id"),
            "project_id": l.get("project_id"), "unit_id": l.get("unit_id"), "notes": l.get("notes")})
        for src in l.get("sources", []):
            if not has_perm(user, "override_qty"):
                mline = await db.mro_lines.find_one({"id": src["line_id"]})
                if mline:
                    rem = mline.get("qty", 0) - await alloc_out(src["line_id"], "ro")
                    if src["qty"] > rem + 1e-6:
                        raise HTTPException(400, "Qty RO melebihi kebutuhan MRO")
            await create_alloc("mro", src["line_id"], src["mro_id"], "ro", lid, did, float(src["qty"]), l["item_id"])
    await audit(user, "create", "ro", did, no)
    await notify("RO baru", f"{no} dibuat, menunggu PO", "ro", body.get("division_id"))
    return await get_ro(did, user)


@api.post("/ro/{did}/submit")
async def submit_ro(did: str, user=Depends(current_user)):
    require(user, "submit")
    await db.ro.update_one({"id": did}, {"$set": {"submitted": True}})
    await audit(user, "submit", "ro", did)
    return await get_ro(did, user)


@api.post("/ro/{did}/cancel")
async def cancel_ro(did: str, body: dict = None, user=Depends(current_user)):
    require(user, "cancel")
    await db.ro.update_one({"id": did}, {"$set": {"cancelled": True}})
    await audit(user, "cancel", "ro", did, reason=(body or {}).get("reason"))
    return {"ok": True}


@api.get("/pull/ro-for-po")
async def pull_ro_for_po(user=Depends(current_user)):
    m = await maps(); out = []
    ros = await db.ro.find({"submitted": True, "cancelled": {"$ne": True}}, {"_id": 0}).to_list(1000)
    for d in ros:
        for l in await db.ro_lines.find({"ro_id": d["id"]}, {"_id": 0}).to_list(500):
            ordered = await alloc_out(l["id"], "po")
            outstanding = l.get("qty", 0) - ordered
            if outstanding > 0:
                enrich_line(l, m)
                srcs = await db.allocations.find({"target_line_id": l["id"], "source_type": "mro"}, {"_id": 0}).to_list(50)
                mro_no = None
                if srcs:
                    mh = await db.mro.find_one({"id": srcs[0]["source_doc_id"]}, {"_id": 0})
                    mro_no = mh["no"] if mh else None
                out.append({"ro_id": d["id"], "ro_no": d["no"], "mro_no": mro_no, "line_id": l["id"],
                    "item_id": l["item_id"], "item_code": l["item_code"], "item_name": l["item_name"],
                    "unit": l["unit"], "qty_ro": l["qty"], "ordered": ordered, "outstanding": outstanding,
                    "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"),
                    "unit_id": l.get("unit_id"), "warehouse_name": l.get("warehouse_name"),
                    "project_name": l.get("project_name")})
    return out


# ---------------- PO ----------------
async def po_line_state(line):
    received = await alloc_out(line["id"], "do")
    return {"qty": line.get("qty", 0), "received": received, "outstanding": max(0, line.get("qty", 0) - received)}


@api.get("/po")
async def list_po(user=Depends(current_user)):
    require(user, "view")
    docs = await db.po.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    m = await maps()
    show_price = has_perm(user, "view_purchase_price")
    for d in docs:
        lines = await db.po_lines.find({"po_id": d["id"]}, {"_id": 0}).to_list(500)
        d["line_count"] = len(lines)
        d["supplier_name"] = m["suppliers"].get(d.get("supplier_id"), {}).get("name")
        d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
        if not show_price:
            d["grand_total"] = None
    return docs


@api.get("/po/{did}")
async def get_po(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.po.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "PO tidak ditemukan")
    m = await maps()
    show_price = has_perm(user, "view_purchase_price")
    lines = await db.po_lines.find({"po_id": did}, {"_id": 0}).to_list(500)
    for l in lines:
        enrich_line(l, m)
        st = await po_line_state(l); l.update(st)
        srcs = await db.allocations.find({"target_line_id": l["id"], "source_type": "ro"}, {"_id": 0}).to_list(50)
        refs = []
        for s in srcs:
            rh = await db.ro.find_one({"id": s["source_doc_id"]}, {"_id": 0})
            if rh:
                mm = await db.allocations.find({"target_line_id": s["source_line_id"], "source_type": "mro"}, {"_id": 0}).to_list(10)
                mro_no = None
                if mm:
                    mh = await db.mro.find_one({"id": mm[0]["source_doc_id"]}, {"_id": 0}); mro_no = mh["no"] if mh else None
                refs.append({"ro_no": rh["no"], "ro_id": rh["id"], "mro_no": mro_no, "qty": s["qty"]})
        l["ro_refs"] = refs
        if not show_price:
            for k in ("price","discount","tax","total"): l[k] = None
    d["lines"] = lines
    d["supplier_name"] = m["suppliers"].get(d.get("supplier_id"), {}).get("name")
    d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
    d["approvals"] = await db.po_approvals.find({"po_id": did}, {"_id": 0}).sort("seq", 1).to_list(50)
    if not show_price:
        d["grand_total"] = None
    return d


@api.post("/po")
async def create_po(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid(); no = await next_number("PO")
    grand = 0
    lines_in = body.get("lines", [])
    for l in lines_in:
        qty = float(l.get("qty", 0)); price = float(l.get("price", 0))
        disc = float(l.get("discount", 0)); tax = float(l.get("tax", 0))
        base = qty * price - disc
        l["total"] = base + base * tax / 100.0
        grand += l["total"]
    await db.po.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "supplier_id": body.get("supplier_id"), "division_id": body.get("division_id"),
        "payment_term": body.get("payment_term"), "eta": body.get("eta"),
        "default_warehouse_id": body.get("default_warehouse_id"), "default_project_id": body.get("default_project_id"),
        "currency": body.get("currency", "IDR"), "tax_pct": body.get("tax_pct", 0),
        "supplier_notes": body.get("supplier_notes"), "internal_notes": body.get("internal_notes"),
        "grand_total": grand, "status": "Draft", "cancelled": False,
        "created_by": user.get("email"), "created_at": now_iso()})
    for l in lines_in:
        lid = gid()
        await db.po_lines.insert_one({"id": lid, "po_id": did, "item_id": l["item_id"],
            "qty": float(l.get("qty", 0)), "unit": l.get("unit"),
            "warehouse_id": l.get("warehouse_id") or body.get("default_warehouse_id"),
            "project_id": l.get("project_id"), "unit_id": l.get("unit_id"), "spk": l.get("spk"),
            "price": float(l.get("price", 0)), "discount": float(l.get("discount", 0)),
            "tax": float(l.get("tax", 0)), "total": l.get("total", 0), "notes": l.get("notes")})
        for src in l.get("sources", []):
            if not has_perm(user, "override_qty"):
                rline = await db.ro_lines.find_one({"id": src["line_id"]})
                if rline:
                    rem = rline.get("qty", 0) - await alloc_out(src["line_id"], "po")
                    if src["qty"] > rem + 1e-6:
                        raise HTTPException(400, "Qty PO melebihi Qty RO")
            await create_alloc("ro", src["line_id"], src["ro_id"], "po", lid, did, float(src["qty"]), l["item_id"])
    await audit(user, "create", "po", did, no, after={"grand_total": grand})
    return await get_po(did, user)


async def _po_required_approvers(amount):
    cfg = await db.settings.find_one({"id": "approval_rules"}) or {}
    for rule in cfg.get("rules", []):
        if rule.get("max") is None or amount <= rule["max"]:
            return rule.get("approvers", [])
    return []


@api.post("/po/{did}/submit")
async def submit_po(did: str, user=Depends(current_user)):
    require(user, "submit")
    d = await db.po.find_one({"id": did})
    if not d: raise HTTPException(404, "PO tidak ditemukan")
    approvers = await _po_required_approvers(d.get("grand_total", 0))
    await db.po_approvals.delete_many({"po_id": did})
    for i, role in enumerate(approvers):
        await db.po_approvals.insert_one({"id": gid(), "po_id": did, "seq": i + 1, "role": role,
            "status": "Pending" if i == 0 else "Waiting", "acted_by": None, "acted_at": None, "note": None})
    status = "Waiting Approval" if approvers else "Approved"
    await db.po.update_one({"id": did}, {"$set": {"status": status}})
    await audit(user, "submit", "po", did, d.get("no"))
    await notify("PO menunggu approval", f"{d['no']} perlu persetujuan", "approval", d.get("division_id"))
    return await get_po(did, user)


@api.post("/po/{did}/approve")
async def approve_po(did: str, body: dict = None, user=Depends(current_user)):
    require(user, "approve")
    d = await db.po.find_one({"id": did})
    if not d: raise HTTPException(404, "PO tidak ditemukan")
    step = await db.po_approvals.find_one({"po_id": did, "status": "Pending"}, sort=[("seq", 1)])
    if not step:
        raise HTTPException(400, "Tidak ada tahap approval yang menunggu")
    await db.po_approvals.update_one({"id": step["id"]}, {"$set": {"status": "Approved",
        "acted_by": user.get("name"), "acted_at": now_iso(), "note": (body or {}).get("note")}})
    nxt = await db.po_approvals.find_one({"po_id": did, "status": "Waiting"}, sort=[("seq", 1)])
    if nxt:
        await db.po_approvals.update_one({"id": nxt["id"]}, {"$set": {"status": "Pending"}})
        await db.po.update_one({"id": did}, {"$set": {"status": "Waiting Approval"}})
    else:
        await db.po.update_one({"id": did}, {"$set": {"status": "Approved"}})
        await notify("PO disetujui", f"{d['no']} approved", "approval", d.get("division_id"))
    await audit(user, "approve", "po", did, d.get("no"))
    return await get_po(did, user)


@api.post("/po/{did}/reject")
async def reject_po(did: str, body: dict = None, user=Depends(current_user)):
    require(user, "reject")
    d = await db.po.find_one({"id": did})
    step = await db.po_approvals.find_one({"po_id": did, "status": "Pending"}, sort=[("seq", 1)])
    if step:
        await db.po_approvals.update_one({"id": step["id"]}, {"$set": {"status": "Rejected",
            "acted_by": user.get("name"), "acted_at": now_iso(), "note": (body or {}).get("reason")}})
    await db.po.update_one({"id": did}, {"$set": {"status": "Rejected"}})
    await audit(user, "reject", "po", did, d.get("no") if d else None, reason=(body or {}).get("reason"))
    await notify("PO ditolak", f"{d['no']} rejected", "approval", d.get("division_id") if d else None)
    return await get_po(did, user)


@api.post("/po/{did}/cancel")
async def cancel_po(did: str, body: dict = None, user=Depends(current_user)):
    require(user, "cancel")
    await db.po.update_one({"id": did}, {"$set": {"status": "Cancelled", "cancelled": True}})
    await audit(user, "cancel", "po", did, reason=(body or {}).get("reason"))
    return {"ok": True}


@api.get("/pull/po-for-do")
async def pull_po_for_do(user=Depends(current_user), supplier_id: str = None):
    m = await maps(); out = []
    query = {"status": {"$in": ["Approved", "Partially Received"]}, "cancelled": {"$ne": True}}
    if supplier_id:
        query["supplier_id"] = supplier_id
    pos = await db.po.find(query, {"_id": 0}).to_list(1000)
    for d in pos:
        for l in await db.po_lines.find({"po_id": d["id"]}, {"_id": 0}).to_list(500):
            received = await alloc_out(l["id"], "do")
            outstanding = l.get("qty", 0) - received
            if outstanding > 0:
                enrich_line(l, m)
                out.append({"po_id": d["id"], "po_no": d["no"], "supplier_id": d.get("supplier_id"),
                    "supplier_name": m["suppliers"].get(d.get("supplier_id"), {}).get("name"),
                    "line_id": l["id"], "item_id": l["item_id"], "item_code": l["item_code"],
                    "item_name": l["item_name"], "unit": l["unit"], "spk": l.get("spk"),
                    "qty_po": l["qty"], "received": received, "outstanding": outstanding,
                    "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"),
                    "unit_id": l.get("unit_id"), "warehouse_name": l.get("warehouse_name")})
    return out


# ---------------- DO ----------------
@api.get("/do")
async def list_do(user=Depends(current_user)):
    require(user, "view")
    docs = await db.do.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    m = await maps()
    for d in docs:
        d["supplier_name"] = m["suppliers"].get(d.get("supplier_id"), {}).get("name")
        d["line_count"] = await db.do_lines.count_documents({"do_id": d["id"]})
    return docs


@api.get("/do/{did}")
async def get_do(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.do.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "DO tidak ditemukan")
    m = await maps()
    lines = await db.do_lines.find({"do_id": did}, {"_id": 0}).to_list(500)
    for l in lines:
        enrich_line(l, m)
        ph = await db.po.find_one({"id": l.get("po_id")}, {"_id": 0})
        l["po_no"] = ph["no"] if ph else None
    d["lines"] = lines
    d["supplier_name"] = m["suppliers"].get(d.get("supplier_id"), {}).get("name")
    return d


async def _refresh_po_receipt_status(po_id):
    lines = await db.po_lines.find({"po_id": po_id}, {"_id": 0}).to_list(500)
    tot = sum(l.get("qty", 0) for l in lines)
    rec = 0
    for l in lines:
        rec += await alloc_out(l["id"], "do")
    po = await db.po.find_one({"id": po_id})
    if not po or po.get("status") in ("Cancelled", "Rejected"): return
    status = po.get("status")
    if rec >= tot and tot > 0:
        status = "Fully Received"
    elif rec > 0:
        status = "Partially Received"
    await db.po.update_one({"id": po_id}, {"$set": {"status": status}})


@api.post("/do")
async def create_do(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid(); no = await next_number("DO")
    await db.do.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "supplier_id": body.get("supplier_id"), "supplier_dn": body.get("supplier_dn"),
        "supplier_invoice": body.get("supplier_invoice"), "invoice_date": body.get("invoice_date"),
        "default_warehouse_id": body.get("default_warehouse_id"), "default_project_id": body.get("default_project_id"),
        "receiver": body.get("receiver", user.get("name")), "notes": body.get("notes"),
        "status": "Posted", "created_by": user.get("email"), "created_at": now_iso()})
    po_ids = set()
    for l in body.get("lines", []):
        qty = float(l.get("qty", 0))
        if qty <= 0: continue
        po_line = await db.po_lines.find_one({"id": l["po_line_id"]})
        if not has_perm(user, "override_qty") and po_line:
            rem = po_line.get("qty", 0) - await alloc_out(l["po_line_id"], "do")
            if qty > rem + 1e-6:
                raise HTTPException(400, "Qty terima melebihi Qty PO")
        lid = gid()
        wh = l.get("warehouse_id") or body.get("default_warehouse_id")
        await db.do_lines.insert_one({"id": lid, "do_id": did, "po_id": l.get("po_id"),
            "po_line_id": l["po_line_id"], "item_id": l["item_id"], "qty": qty, "unit": l.get("unit"),
            "warehouse_id": wh, "project_id": l.get("project_id"), "unit_id": l.get("unit_id"),
            "spk": l.get("spk"), "condition": l.get("condition", "Baik"), "notes": l.get("notes")})
        await create_alloc("po", l["po_line_id"], l.get("po_id"), "do", lid, did, qty, l["item_id"])
        await post_ledger("DO", no, did, l["item_id"], wh, qty, 0,
                          project_id=l.get("project_id"), unit_id=l.get("unit_id"), user=user)
        if l.get("po_id"): po_ids.add(l["po_id"])
    for pid in po_ids:
        await _refresh_po_receipt_status(pid)
    await audit(user, "create", "do", did, no)
    await notify("Barang diterima", f"DO {no} diposting", "do", None)
    return await get_do(did, user)


# ---------------- MI ----------------
@api.get("/mi")
async def list_mi(user=Depends(current_user)):
    require(user, "view")
    docs = await db.mi.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    m = await maps()
    for d in docs:
        d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
        d["line_count"] = await db.mi_lines.count_documents({"mi_id": d["id"]})
    return docs


@api.get("/mi/{did}")
async def get_mi(did: str, user=Depends(current_user)):
    require(user, "view")
    d = await db.mi.find_one({"id": did}, {"_id": 0})
    if not d: raise HTTPException(404, "MI tidak ditemukan")
    m = await maps()
    lines = await db.mi_lines.find({"mi_id": did}, {"_id": 0}).to_list(500)
    for l in lines:
        enrich_line(l, m)
        if l.get("mro_line_id"):
            srcs = await db.allocations.find({"target_line_id": l["id"], "source_type": "mro"}, {"_id": 0}).to_list(10)
            if srcs:
                mh = await db.mro.find_one({"id": srcs[0]["source_doc_id"]}, {"_id": 0})
                l["mro_no"] = mh["no"] if mh else None
    d["lines"] = lines
    d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
    return d


@api.post("/mi")
async def create_mi(body: dict, user=Depends(current_user)):
    require(user, "create")
    source_type = body.get("source_type", "MRO")
    if source_type == "Direct":
        require(user, "direct_mi")
    did = gid(); no = await next_number("MI")
    await db.mi.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "division_id": body.get("division_id"), "default_warehouse_id": body.get("default_warehouse_id"),
        "default_project_id": body.get("default_project_id"), "receiver": body.get("receiver"),
        "department": body.get("department"), "source_type": source_type, "notes": body.get("notes"),
        "status": "Posted", "created_by": user.get("email"), "created_at": now_iso()})
    for l in body.get("lines", []):
        qty = float(l.get("qty", 0))
        if qty <= 0: continue
        wh = l.get("warehouse_id") or body.get("default_warehouse_id")
        avail = await stock_balance(l["item_id"], wh)
        if qty > avail + 1e-6 and not has_perm(user, "override_qty"):
            raise HTTPException(400, f"Stok tidak cukup (tersedia {avail})")
        if l.get("mro_line_id"):
            mline = await db.mro_lines.find_one({"id": l["mro_line_id"]})
            if mline and not has_perm(user, "override_qty"):
                rem = mline.get("qty", 0) - await alloc_out(l["mro_line_id"], "mi")
                if qty > rem + 1e-6:
                    raise HTTPException(400, "Qty MI melebihi kebutuhan MRO")
        lid = gid()
        await db.mi_lines.insert_one({"id": lid, "mi_id": did, "mro_line_id": l.get("mro_line_id"),
            "item_id": l["item_id"], "qty": qty, "unit": l.get("unit"), "warehouse_id": wh,
            "project_id": l.get("project_id"), "unit_id": l.get("unit_id"), "notes": l.get("notes")})
        if l.get("mro_line_id"):
            await create_alloc("mro", l["mro_line_id"], l.get("mro_id"), "mi", lid, did, qty, l["item_id"])
        await post_ledger("MI", no, did, l["item_id"], wh, 0, qty,
                          project_id=l.get("project_id"), unit_id=l.get("unit_id"),
                          division_id=body.get("division_id"), user=user)
    await audit(user, "create", "mi", did, no)
    await notify("Barang dikeluarkan", f"MI {no} diposting", "mi", body.get("division_id"))
    return await get_mi(did, user)
