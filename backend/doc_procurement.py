"""MRO, RO, PO, DO, MI + PO approval workflow."""
import asyncio
from fastapi import Depends, HTTPException
from server import (api, db, gid, now_iso, clean, current_user, require, has_perm,
                    is_global, audit, notify, next_number, alloc_out, create_alloc,
                    post_ledger, stock_balance)


async def maps():
    import mariadb_motor
    cache = mariadb_motor.REQ_CACHE.get()
    if cache is not None and "maps" in cache:
        return cache["maps"]
    out = await _load_maps()
    if cache is not None:
        cache["maps"] = out
    return out


async def _load_maps():
    # 7 referensi independen dimuat paralel (1 round-trip efektif, bukan 7 berurutan).
    names = [("items", 5000), ("warehouses", 2000), ("projects", 2000), ("units", 2000), ("divisions", 500), ("suppliers", 2000), ("uoms", 2000)]
    res = await asyncio.gather(*(getattr(db, n).find({}, {"_id": 0}).to_list(lim) for n, lim in names))
    return {n: {d["id"]: d for d in rows} for (n, _), rows in zip(names, res)}


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


# ---- batch helpers (hindari N+1: satu query per relasi untuk seluruh baris) ----
async def lines_by_doc(coll, fk, ids):
    out = {i: [] for i in ids}
    if ids:
        for l in await getattr(db, coll).find({fk: {"$in": list(ids)}}, {"_id": 0}).to_list(None):
            out.setdefault(l.get(fk), []).append(l)
    return out


async def allocs_from(source_line_ids, target_type):
    ids = [x for x in set(source_line_ids) if x]
    if not ids:
        return {}
    out = {}
    for a in await db.allocations.find({"source_line_id": {"$in": ids}, "target_type": target_type}, {"_id": 0}).to_list(None):
        out.setdefault(a.get("source_line_id"), []).append(a)
    return out


def _sum(allocs):
    return sum(a.get("qty") or 0 for a in allocs or [])


async def mro_monitor_batch(lines):
    """Sama dengan mro_line_monitor, tetapi 4 query total untuk seluruh baris."""
    lids = [l["id"] for l in lines]
    to_ro, to_mi = await asyncio.gather(allocs_from(lids, "ro"), allocs_from(lids, "mi"))
    ro_lids = [a["target_line_id"] for v in to_ro.values() for a in v]
    to_po = await allocs_from(ro_lids, "po")
    to_do = await allocs_from([a["target_line_id"] for v in to_po.values() for a in v], "do")
    out = {}
    for l in lines:
        qty = l.get("qty", 0); qty_po = 0; qty_received = 0
        for a in to_ro.get(l["id"], []):
            rl = a["target_line_id"]; portion = a["qty"]
            qty_po += min(portion, _sum(to_po.get(rl)))
            rec = sum(_sum(to_do.get(pa["target_line_id"])) for pa in to_po.get(rl, []))
            qty_received += min(portion, rec)
        qty_mi = _sum(to_mi.get(l["id"]))
        out[l["id"]] = {"qty_request": qty, "qty_ro": _sum(to_ro.get(l["id"])), "qty_po": qty_po,
                        "qty_received": qty_received, "qty_mi": qty_mi, "outstanding": max(0, qty - qty_mi)}
    return out


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
    by_doc = await lines_by_doc("mro_lines", "mro_id", [d["id"] for d in docs])
    monitor = await mro_monitor_batch([l for v in by_doc.values() for l in v])
    for d in docs:
        lines = by_doc.get(d["id"], [])
        mon = [monitor[l["id"]] for l in lines]
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


@api.post("/po/price-control")
async def po_price_control(body: dict, user=Depends(current_user)):
    """CP5A-2 — batch resolve Vendor Contract Price (CP3 resolver) for PO lines.
    Returns contract price + effective tolerance per line so the frontend can
    compute variance & status (Normal / Price Override / No Contract).
    Read-only; never mutates the contract master."""
    require(user, "view_purchase_price")
    import server as _srv
    resolver = getattr(_srv, "resolve_vendor_contract_price", None)
    period_hint = getattr(_srv, "resolve_contract_period_hint", None)
    supplier_id = (body or {}).get("supplier_id") or ""
    date = (body or {}).get("date") or None
    out = []
    for ln in (body or {}).get("lines", []) or []:
        key = ln.get("key")
        item_id = ln.get("item_id"); uom_id = ln.get("uom_id"); qty = ln.get("qty")
        res = None
        if resolver and supplier_id and item_id and uom_id:
            try:
                res = await resolver(supplier_id, item_id, uom_id, date, qty)
            except Exception:
                res = None
        if res:
            out.append({"key": key, "found": True,
                        "contract_number": res.get("contract_number"),
                        "contract_price": res.get("net_contract_price"),
                        "tolerance_pct": res.get("tolerance_pct"),
                        "effective_start": res.get("effective_start"),
                        "effective_end": res.get("effective_end"),
                        "min_qty": res.get("min_qty"),
                        "currency": res.get("currency")})
        else:
            # Contract Period Guard (CP5A follow-up): surface a non-blocking hint when an active
            # contract exists for this item but the PO date is outside its effective period.
            hint = None
            if period_hint and supplier_id and item_id and uom_id:
                try:
                    hint = await period_hint(supplier_id, item_id, uom_id, date)
                except Exception:
                    hint = None
            row = {"key": key, "found": False}
            if hint:
                row.update({"out_of_period": True,
                            "contract_number": hint.get("contract_number"),
                            "effective_start": hint.get("effective_start"),
                            "effective_end": hint.get("effective_end"),
                            "position": hint.get("position")})
            out.append(row)
    return {"lines": out}


@api.get("/purchase-price-history")
async def purchase_price_history(item_id: str, uom_id: str = "", supplier_id: str = "",
                                 scope: str = "all", limit: int = 20, summary: int = 0,
                                 user=Depends(current_user)):
    """CP5A-1 — read-only purchase price history (decision support only).
    Only valid purchasing records count (Approved / received). Draft/Rejected/
    Cancelled are excluded. This is NOT the Price Override rule (that uses the
    vendor contract price, added in CP5A-2)."""
    require(user, "view_purchase_price")
    VALID = ["Approved", "Partially Received", "Fully Received"]
    pos = await db.po.find({"status": {"$in": VALID}, "cancelled": {"$ne": True}}).to_list(1000)
    po_by_id = {p["id"]: p for p in pos}
    sup_docs = await db.suppliers.find({}).to_list(2000)
    sup_name = {s["id"]: s.get("name") for s in sup_docs}
    lq = {"item_id": item_id}
    if uom_id:
        lq["uom_id"] = uom_id
    lines = await db.po_lines.find(lq).to_list(3000)
    rows = []
    for l in lines:
        p = po_by_id.get(l.get("po_id"))
        if not p:
            continue
        sid = p.get("supplier_id")
        if scope == "vendor" and supplier_id and sid != supplier_id:
            continue
        factor = float(l.get("conversion_factor") or 1) or 1
        unit_price = l.get("display_price")
        if unit_price is None:
            unit_price = (float(l.get("price") or 0) * factor)
        rows.append({
            "date": p.get("date"), "po_id": p.get("id"), "po_no": p.get("no"),
            "supplier_id": sid, "supplier_name": sup_name.get(sid) or "-",
            "qty": l.get("display_qty", (float(l.get("qty") or 0) / factor)),
            "uom": l.get("display_unit") or l.get("unit") or "",
            "uom_id": l.get("uom_id"),
            "unit_price": float(unit_price or 0),
        })
    rows.sort(key=lambda r: (r.get("date") or ""), reverse=True)
    last = rows[0] if rows else None
    if summary:
        return {"last": last, "count": len(rows)}
    return {"rows": rows[:max(1, min(limit, 100))], "last": last, "count": len(rows)}


@api.post("/mro")
async def create_mro(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid()
    # Manual MRO number (hard validation) — replaces legacy auto-numbering.
    no = (body.get("no") or "").strip()
    if not no:
        raise HTTPException(400, "Nomor MRO wajib diisi sebelum transaksi disimpan.")
    # Tenant-scoped uniqueness (db proxy auto-scopes by tenant_id).
    if await db.mro.find_one({"no": no}):
        raise HTTPException(400, f'Nomor MRO "{no}" sudah digunakan. Silakan gunakan nomor lain.')
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
    by_doc = await lines_by_doc("ro_lines", "ro_id", [d["id"] for d in docs])
    ordered = await allocs_from([l["id"] for v in by_doc.values() for l in v], "po")
    for d in docs:
        lines = by_doc.get(d["id"], [])
        states = [{"qty": l.get("qty", 0), "ordered": _sum(ordered.get(l["id"])),
                   "outstanding": max(0, l.get("qty", 0) - _sum(ordered.get(l["id"])))} for l in lines]
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
    by_doc = await lines_by_doc("po_lines", "po_id", [d["id"] for d in docs])
    for d in docs:
        d["line_count"] = len(by_doc.get(d["id"], []))
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
            for k in ("price","discount","tax","total","contract_price_snapshot","price_variance","price_variance_pct"): l[k] = None
    d["lines"] = lines
    d["supplier_name"] = m["suppliers"].get(d.get("supplier_id"), {}).get("name")
    d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
    d["approvals"] = await db.po_approvals.find({"po_id": did}, {"_id": 0}).sort("seq", 1).to_list(50)
    if not show_price:
        d["grand_total"] = None
    return d


def _po_final_discount_amount(subtotal_after_item, ftype, fvalue):
    """Diskon Final level-PO. Persen dihitung dari Subtotal Setelah Diskon Item;
    Rp langsung (tidak boleh melebihi subtotal)."""
    fv = float(fvalue or 0)
    base = max(0.0, float(subtotal_after_item or 0))
    if fv <= 0 or base <= 0:
        return 0.0
    if str(ftype or "").lower() in ("percent", "%", "persen", "pct"):
        return min(base, base * fv / 100.0)
    return min(base, fv)


def compute_po_totals(header, lines):
    """Canonical PO money engine (shared by create_po + transaction update + preview).
    Item discount (amount) is subtracted first, then the PO-level Final Discount is PRORATED
    across each line's net (taxable base) before tax, so per-line `total` (and therefore the
    SPK commitment that reads po_lines.total) always reconciles with the header grand_total.
    Preserves the existing tax model: exclusive adds tax on the discounted base; inclusive
    extracts tax from the discounted price (never double-added)."""
    inclusive = bool(header.get("tax_inclusive"))
    nets = []; gross_total = 0.0; item_disc_total = 0.0
    for l in lines:
        qty = float(l.get("qty") or 0); price = float(l.get("price") or 0)
        disc = float(l.get("discount") or 0)
        gross = qty * price; net = max(0.0, gross - disc)
        gross_total += gross; item_disc_total += disc; nets.append(net)
    subtotal_after_item = sum(nets)
    fd_amount = _po_final_discount_amount(subtotal_after_item, header.get("final_discount_type"), header.get("final_discount_value"))
    factor = ((subtotal_after_item - fd_amount) / subtotal_after_item) if subtotal_after_item > 0 else 1.0
    out = []; grand = 0.0; tax_total = 0.0; subtotal_after_final = 0.0
    for l, net in zip(lines, nets):
        rate = float(l.get("tax") or 0); net_final = net * factor
        if inclusive and rate:
            dpp = net_final / (1 + rate / 100.0); tax_amount = net_final - dpp; total = net_final
        else:
            dpp = net_final; tax_amount = dpp * rate / 100.0; total = dpp + tax_amount
        subtotal_after_final += net_final; tax_total += tax_amount; grand += total
        x = dict(l)
        x["gross"] = float(l.get("qty") or 0) * float(l.get("price") or 0)
        x["dpp"] = dpp; x["tax_amount"] = tax_amount; x["total"] = total; x["tax_inclusive"] = inclusive
        out.append(x)
    totals = {"gross_total": gross_total, "item_discount_total": item_disc_total,
              "subtotal_after_item_discount": subtotal_after_item,
              "final_discount_type": (header.get("final_discount_type") or None),
              "final_discount_value": float(header.get("final_discount_value") or 0),
              "final_discount_amount": fd_amount, "subtotal_after_discount": subtotal_after_final,
              "tax_total": tax_total, "grand_total": grand}
    return out, totals


@api.post("/po")
async def create_po(body: dict, user=Depends(current_user)):
    require(user, "create")
    did = gid(); no = await next_number("PO")
    lines_in = body.get("lines", [])
    computed, totals = compute_po_totals(body, lines_in)
    for l, c in zip(lines_in, computed):
        l["total"] = c["total"]
    grand = totals["grand_total"]
    await db.po.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "supplier_id": body.get("supplier_id"), "division_id": body.get("division_id"),
        "payment_term": body.get("payment_term"), "eta": body.get("eta"),
        "default_warehouse_id": body.get("default_warehouse_id"), "default_project_id": body.get("default_project_id"),
        "currency": body.get("currency", "IDR"), "tax_pct": body.get("tax_pct", 0),
        "tax_inclusive": bool(body.get("tax_inclusive", False)),
        "supplier_notes": body.get("supplier_notes"), "internal_notes": body.get("internal_notes"),
        "final_discount_type": totals["final_discount_type"], "final_discount_value": totals["final_discount_value"],
        "final_discount_amount": totals["final_discount_amount"],
        "gross_total": totals["gross_total"], "item_discount_total": totals["item_discount_total"],
        "subtotal_after_item_discount": totals["subtotal_after_item_discount"],
        "subtotal_after_discount": totals["subtotal_after_discount"], "tax_total": totals["tax_total"],
        "grand_total": grand, "status": "Draft", "cancelled": False,
        "created_by": user.get("email"), "created_at": now_iso()})
    for l, c in zip(lines_in, computed):
        lid = gid()
        await db.po_lines.insert_one({"id": lid, "po_id": did, "item_id": l["item_id"],
            "qty": float(l.get("qty", 0)), "unit": l.get("unit"),
            "warehouse_id": l.get("warehouse_id") or body.get("default_warehouse_id"),
            "project_id": l.get("project_id"), "unit_id": l.get("unit_id"), "spk": l.get("spk"),
            "price": float(l.get("price", 0)), "discount": float(l.get("discount", 0)),
            "discount_type": (l.get("discount_type") or None), "discount_value": float(l.get("discount_value") or 0),
            "discount_amount": float(l.get("discount", 0)),
            "dpp": c["dpp"], "tax_amount": c["tax_amount"], "tax_inclusive": c["tax_inclusive"],
            "tax": float(l.get("tax", 0)), "total": c["total"], "notes": l.get("notes"),
            "price_change_reason": (l.get("price_change_reason") or None),
            "contract_price_snapshot": l.get("contract_price_snapshot"),
            "contract_number_snapshot": l.get("contract_number_snapshot"),
            "price_variance": l.get("price_variance"),
            "price_variance_pct": l.get("price_variance_pct"),
            "price_status": l.get("price_status")})
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


async def assert_po_price_reason(did: str):
    """CP5A-2/3 hard-block (reusable): if an applicable vendor contract exists, Harga Satuan
    differs from the contract price, and the price-change reason is empty -> block.
    Safe to call from any PO submit path (approval workflow enabled OR disabled), since the
    approval layer may finalize PO without routing through submit_po().

    Returns the list of price-override lines (contract found + price differs, reason PRESENT)
    so callers can write an audit/approval-log trail. Raises HTTP 400 if any reason is missing."""
    d = await db.po.find_one({"id": did})
    if not d:
        return []
    import server as _srv
    _resolver = getattr(_srv, "resolve_vendor_contract_price", None)
    if not (_resolver and d.get("supplier_id")):
        return []
    _plines = await db.po_lines.find({"po_id": did}, {"_id": 0}).to_list(500)
    overrides = []
    for _l in _plines:
        _item = _l.get("item_id"); _uom = _l.get("uom_id")
        if not _item or not _uom:
            continue
        _f = float(_l.get("conversion_factor") or 1) or 1
        _dqty = _l.get("display_qty")
        _dqty = float(_dqty) if _dqty is not None else (float(_l.get("qty") or 0) / _f)
        try:
            _res = await _resolver(d.get("supplier_id"), _item, _uom, d.get("date"), _dqty)
        except Exception:
            _res = None
        if not _res:
            continue
        _cp = float(_res.get("net_contract_price") or 0)
        _dp = _l.get("display_price")
        _dp = float(_dp) if _dp is not None else (float(_l.get("price") or 0) * _f)
        # Effective unit price AFTER item discount (Final Discount is PO-level and NEVER
        # affects per-item contract comparison). Compare effective price vs contract + tolerance.
        _disc = float(_l.get("discount") or 0)
        _eff = (((_dqty * _dp) - _disc) / _dqty) if _dqty > 0 else _dp
        _tol = float(_res.get("tolerance_pct") or 0)
        _varpct = ((_eff - _cp) / _cp * 100.0) if _cp else 0.0
        if _cp and _varpct > _tol + 1e-9:  # Price Override (effective price beyond tolerance)
            _reason = str(_l.get("price_change_reason") or "").strip()
            if not _reason:
                raise HTTPException(400, "Alasan perubahan harga wajib diisi karena Harga Satuan berbeda dari Harga Kontrak.")
            overrides.append({
                "item_name": _res.get("item_name") or _l.get("item_name") or _l.get("item_code") or _item,
                "contract_number": _res.get("contract_number"),
                "contract_price": _cp, "po_price": _dp, "item_discount": round(_disc, 2),
                "effective_unit_price": round(_eff, 2),
                "variance": round(_eff - _cp, 2), "variance_pct": round(_varpct, 2),
                "tolerance_pct": _tol, "reason": _reason,
            })
    return overrides


async def log_po_price_overrides(did: str, user, overrides):
    """Write a per-line audit/approval-log entry for each price-override reason so the trail
    shows up in the PO activity/audit timeline (AuditPanel reads /audit?entity=po&entity_id=)."""
    if not overrides:
        return
    d = await db.po.find_one({"id": did}) or {}
    no = d.get("no")
    for o in overrides:
        await audit(user, "price_override", "po", did, no,
                    after={"item": o.get("item_name"), "contract_number": o.get("contract_number"),
                           "contract_price": o.get("contract_price"), "po_price": o.get("po_price"),
                           "item_discount": o.get("item_discount"), "effective_unit_price": o.get("effective_unit_price"),
                           "variance": o.get("variance"), "variance_pct": o.get("variance_pct"),
                           "tolerance_pct": o.get("tolerance_pct")},
                    reason=f"Perubahan harga {o.get('item_name')} (efektif {o.get('effective_unit_price')} vs kontrak {o.get('contract_price')}): {o.get('reason')}")


@api.post("/po/{did}/submit")
async def submit_po(did: str, user=Depends(current_user)):
    require(user, "submit")
    d = await db.po.find_one({"id": did})
    if not d: raise HTTPException(404, "PO tidak ditemukan")
    # CP5A-2/3: hard-block submit if an applicable vendor contract exists, Harga Satuan differs,
    # and the price-change reason is empty. Secondary guard to the frontend validation.
    _overrides = await assert_po_price_reason(did)
    await log_po_price_overrides(did, user, _overrides)
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
    by_doc = await lines_by_doc("do_lines", "do_id", [d["id"] for d in docs])
    for d in docs:
        d["supplier_name"] = m["suppliers"].get(d.get("supplier_id"), {}).get("name")
        d["line_count"] = len(by_doc.get(d["id"], []))
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


async def resolve_do_acq_cost(po_line_id, item_id=None, doc_id=None, line_id=None):
    """Resolve the acquisition unit cost for a DO receipt line under Moving Average.

    Priority:
      1. Referenced PO line net per unit = dpp / qty (PO net merchandise value AFTER item discount
         and proportional final discount, EXCLUDING normal creditable VAT).
      2. (edit/re-post only) A prior VERIFIED (non-estimated) DO valuation snapshot for this line.
    If neither resolves, HARD-BLOCK — never estimate / use current avg / latest price.
    """
    if po_line_id:
        pol = await db.po_lines.find_one({"id": po_line_id}, {"_id": 0})
        if pol and float(pol.get("qty") or 0) > 0:
            return float(pol.get("dpp") or 0) / float(pol.get("qty"))
    if doc_id:
        q = {"doc_id": doc_id, "doc_type": "DO", "qty_in": {"$gt": 0}, "valuation_estimated": {"$ne": True}}
        if item_id:
            q["item_id"] = item_id   # line ids are regenerated on edit; match by item within the doc
        prev = await db.valuation_ledger.find(q, {"_id": 0}).sort("at", -1).to_list(1)
        if prev and prev[0].get("unit_cost") not in (None, 0):
            return float(prev[0]["unit_cost"])
    # human-readable context (no UUIDs)
    item = await db.items.find_one({"id": item_id}, {"_id": 0}) if item_id else None
    po_no = None
    if po_line_id:
        pol = await db.po_lines.find_one({"id": po_line_id}, {"_id": 0})
        if pol and pol.get("po_id"):
            po = await db.po.find_one({"id": pol["po_id"]}, {"_id": 0})
            po_no = (po or {}).get("no")
    item_label = (item or {}).get("code") or (item or {}).get("name") or "tidak diketahui"
    raise HTTPException(400,
        "Penerimaan tidak dapat diposting karena sumber harga dari PO tidak ditemukan. "
        "Periksa kembali referensi PO pada item penerimaan. "
        f"(PO: {po_no or 'tidak diketahui'}, Item: {item_label})")


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
            from receipt_control_layer import over_allowed
            if qty > rem + 1e-6 and not over_allowed(l["po_line_id"]):
                raise HTTPException(400, "Qty terima melebihi Qty PO")
        lid = gid()
        wh = l.get("warehouse_id") or body.get("default_warehouse_id")
        await db.do_lines.insert_one({"id": lid, "do_id": did, "po_id": l.get("po_id"),
            "po_line_id": l["po_line_id"], "item_id": l["item_id"], "qty": qty, "unit": l.get("unit"),
            "warehouse_id": wh, "project_id": l.get("project_id"), "unit_id": l.get("unit_id"),
            "spk": l.get("spk"), "condition": l.get("condition", "Baik"), "notes": l.get("notes")})
        await create_alloc("po", l["po_line_id"], l.get("po_id"), "do", lid, did, qty, l["item_id"])
        # Acquisition cost for Moving Average = PO net per unit (after item + final discount, excl tax).
        # Hard-block (no estimated fallback) if the PO source cannot be resolved.
        acq_cost = await resolve_do_acq_cost(l["po_line_id"], item_id=l["item_id"])
        await post_ledger("DO", no, did, l["item_id"], wh, qty, 0,
                          project_id=l.get("project_id"), unit_id=l.get("unit_id"), user=user,
                          unit_cost_in=acq_cost, line_id=lid, uom=l.get("unit"),
                          conversion_factor=l.get("conversion_factor", 1),
                          txn_at=body.get("date"), source_key=f"DO::{lid}", require_cost=True)
        if l.get("po_id"): po_ids.add(l["po_id"])
    for pid in po_ids:
        await _refresh_po_receipt_status(pid)
    await audit(user, "create", "do", did, no)
    await notify("Barang diterima", f"DO {no} diposting", "do", None)
    return await get_do(did, user)


# ---------------- DO monetary traceability (BACKEND / REPORTING ONLY) ----------------
# DO UI is non-nominal. PO stays the source of truth for commercial value.
# These helpers derive receiving value from the referenced PO line (po_id/po_line_id),
# reusing the canonical per-line amounts already persisted by compute_po_totals
# (dpp/tax_amount/total already include the PO Final Discount prorated per line).
# Nothing here mutates PO, PO commitment, or stock.
def _po_line_item_discount(po_line):
    v = po_line.get("discount_amount")
    if v is None:
        v = po_line.get("discount")
    return float(v or 0)


async def compute_do_receiving_value(did, user):
    d = await db.do.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(404, "DO tidak ditemukan")
    m = await maps()
    lines = await db.do_lines.find({"do_id": did}, {"_id": 0}).to_list(500)
    out_lines = []
    tot = {"qty_received": 0.0, "gross": 0.0, "item_discount": 0.0, "final_discount": 0.0,
           "net": 0.0, "tax": 0.0, "total": 0.0}
    for l in lines:
        recv = float(l.get("qty") or 0)
        pl = await db.po_lines.find_one({"id": l.get("po_line_id")}, {"_id": 0}) if l.get("po_line_id") else None
        po = await db.po.find_one({"id": l.get("po_id")}, {"_id": 0}) if l.get("po_id") else None
        base = {"do_line_id": l.get("id"), "po_id": l.get("po_id"), "po_line_id": l.get("po_line_id"),
                "po_no": (po or {}).get("no"), "item_id": l.get("item_id"),
                "item_name": m["items"].get(l.get("item_id"), {}).get("name"),
                "qty_received": recv, "unit": l.get("unit"), "spk": l.get("spk"),
                "project_id": l.get("project_id"), "unit_id": l.get("unit_id"),
                "warehouse_id": l.get("warehouse_id")}
        if not pl:
            base.update({"po_qty": None, "po_unit_price": None, "effective_unit_price": None,
                         "gross_receiving_value": None, "item_discount_attributable": None,
                         "final_discount_attributable": None, "net_receiving_value": None,
                         "tax_attributable": None, "total_receiving_value": None, "tax_inclusive": None,
                         "_note": "PO line tidak ditemukan"})
            out_lines.append(base)
            continue
        po_qty = float(pl.get("qty") or 0)
        ratio = (recv / po_qty) if po_qty > 0 else 0.0
        price = float(pl.get("price") or 0)
        disc_amt = _po_line_item_discount(pl)
        gross_full = po_qty * price
        net_after_item_full = max(0.0, gross_full - disc_amt)
        dpp_full = float(pl.get("dpp") or 0)         # net taxable after item + final discount
        tax_full = float(pl.get("tax_amount") or 0)
        total_full = float(pl.get("total") or 0)
        inclusive = bool(pl.get("tax_inclusive"))
        # Final-discount share attributable to this line (reconciles with compute_po_totals).
        net_value_full = dpp_full if not inclusive else (dpp_full + tax_full)
        final_disc_full = max(0.0, net_after_item_full - net_value_full)
        eff_unit = (net_after_item_full / po_qty) if po_qty > 0 else price
        base.update({
            "po_qty": po_qty, "po_unit_price": price, "item_discount_amount_po": disc_amt,
            "effective_unit_price": eff_unit, "tax_rate": float(pl.get("tax") or 0), "tax_inclusive": inclusive,
            "gross_receiving_value": gross_full * ratio,
            "item_discount_attributable": disc_amt * ratio,
            "final_discount_attributable": final_disc_full * ratio,
            "net_receiving_value": net_value_full * ratio,
            "taxable_basis": dpp_full * ratio,
            "tax_attributable": tax_full * ratio,
            "total_receiving_value": total_full * ratio,
        })
        out_lines.append(base)
        tot["qty_received"] += recv
        tot["gross"] += base["gross_receiving_value"]
        tot["item_discount"] += base["item_discount_attributable"]
        tot["final_discount"] += base["final_discount_attributable"]
        tot["net"] += base["net_receiving_value"]
        tot["tax"] += base["tax_attributable"]
        tot["total"] += base["total_receiving_value"]
    return {"do_id": did, "do_no": d.get("no"), "date": d.get("date"),
            "supplier_id": d.get("supplier_id"),
            "supplier_name": m["suppliers"].get(d.get("supplier_id"), {}).get("name"),
            "lines": out_lines, "totals": tot}


@api.get("/reports/do-receiving/{did}")
async def do_receiving_report(did: str, user=Depends(current_user)):
    """Backend-only monetary view of a DO's receiving value. Gated behind the same
    purchase-price permission as PO pricing so normal receiving users never see nominal."""
    require(user, "view")
    if not has_perm(user, "view_purchase_price"):
        raise HTTPException(403, "Tidak memiliki akses nilai pembelian")
    return await compute_do_receiving_value(did, user)



# ---------------- MI ----------------
@api.get("/mi")
async def list_mi(user=Depends(current_user)):
    require(user, "view")
    docs = await db.mi.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    m = await maps()
    by_doc = await lines_by_doc("mi_lines", "mi_id", [d["id"] for d in docs])
    for d in docs:
        d["division_name"] = m["divisions"].get(d.get("division_id"), {}).get("name")
        d["line_count"] = len(by_doc.get(d["id"], []))
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


# ---------------- MI settings (Direct mode config), stock-per-warehouse, MI trace ----------------
def _is_admin_like(user):
    u = user or {}
    return u.get("role") in ("admin", "director", "purchasing") or "view_all_division" in (u.get("permissions") or [])


async def _mi_settings():
    s = await db.settings.find_one({"id": "mi_settings"}, {"_id": 0}) or {}
    return {"mi_mode": s.get("mi_mode", "mro_only"),
            "direct_authorized_roles": list(s.get("direct_authorized_roles") or []),
            "direct_authorized_user_ids": list(s.get("direct_authorized_user_ids") or [])}


def _can_direct_mi(user, st):
    if st.get("mi_mode") != "mro_plus_direct":
        return False
    if (user or {}).get("role") == "admin":
        return True
    roles = st.get("direct_authorized_roles") or []
    uids = st.get("direct_authorized_user_ids") or []
    if not roles and not uids:
        return has_perm(user, "direct_mi")
    return (user.get("role") in roles) or (user.get("id") in uids) or (user.get("email") in uids)


@api.get("/settings/mi")
async def get_mi_settings(user=Depends(current_user)):
    require(user, "view")
    st = await _mi_settings()
    return {**st, "can_direct": _can_direct_mi(user, st), "can_manage": _is_admin_like(user)}


@api.put("/settings/mi")
async def put_mi_settings(body: dict, user=Depends(current_user)):
    if not _is_admin_like(user):
        raise HTTPException(403, "Hanya admin yang dapat mengubah konfigurasi MI")
    mode = body.get("mi_mode", "mro_only")
    if mode not in ("mro_only", "mro_plus_direct"):
        raise HTTPException(400, "mi_mode tidak valid")
    doc = {"id": "mi_settings", "mi_mode": mode,
           "direct_authorized_roles": list(body.get("direct_authorized_roles") or []),
           "direct_authorized_user_ids": list(body.get("direct_authorized_user_ids") or [])}
    await db.settings.update_one({"id": "mi_settings"}, {"$set": doc}, upsert=True)
    await audit(user, "edit", "settings", "mi_settings", "MI Settings", after=doc)
    return doc


@api.get("/stock/by-warehouse/{item_id}")
async def stock_by_warehouse(item_id: str, user=Depends(current_user)):
    """Read-only on-hand per warehouse for one item (base UOM). Used by MI stock info icon."""
    require(user, "view")
    m = await maps()
    rows = await db.item_warehouse.find({"item_id": item_id}, {"_id": 0}).to_list(1000)
    seen = {}
    for r in rows:
        seen[r.get("warehouse_id")] = float(r.get("current_stock") or 0)
    whs = m.get("warehouses") or {}
    out = [{"warehouse_id": wid, "warehouse_name": w.get("name") or wid, "stock": seen.get(wid, 0.0)}
           for wid, w in whs.items()]
    for wid, stv in seen.items():
        if wid not in whs:
            out.append({"warehouse_id": wid, "warehouse_name": wid, "stock": stv})
    out.sort(key=lambda x: (-x["stock"], x["warehouse_name"] or ""))
    return {"item_id": item_id, "warehouses": out}


@api.get("/reports/mi-trace/{mid}")
async def mi_trace_report(mid: str, user=Depends(current_user)):
    """Non-monetary MI traceability (MI -> MRO; dimensions for reporting). NOTE: no inventory
    valuation basis exists for MI in current architecture, so monetary value is intentionally
    NOT derived here and is reported as a gap (valuation_basis=null)."""
    require(user, "view")
    d = await db.mi.find_one({"id": mid}, {"_id": 0})
    if not d:
        raise HTTPException(404, "MI tidak ditemukan")
    m = await maps()
    lines = await db.mi_lines.find({"mi_id": mid}, {"_id": 0}).to_list(500)
    out = []
    for l in lines:
        mline = await db.mro_lines.find_one({"id": l.get("mro_line_id")}, {"_id": 0}) if l.get("mro_line_id") else None
        mro = await db.mro.find_one({"id": l.get("mro_id") or (mline or {}).get("mro_id")}, {"_id": 0}) if (l.get("mro_id") or mline) else None
        out.append({"mi_line_id": l.get("id"), "item_id": l.get("item_id"),
                    "item_name": m["items"].get(l.get("item_id"), {}).get("name"),
                    "qty_issue": float(l.get("qty") or 0), "unit": l.get("unit"),
                    "warehouse_id": l.get("warehouse_id"),
                    "warehouse_name": m["warehouses"].get(l.get("warehouse_id"), {}).get("name"),
                    "project_id": l.get("project_id"), "unit_id": l.get("unit_id"), "spk": l.get("spk"),
                    "mro_id": l.get("mro_id") or (mline or {}).get("mro_id"), "mro_no": (mro or {}).get("no"),
                    "mro_line_id": l.get("mro_line_id"),
                    "pemohon": (mro or {}).get("requester") or (mro or {}).get("pemohon")})
    return {"mi_id": mid, "mi_no": d.get("no"),
            "source_mode": d.get("source_mode") or ("direct" if d.get("source_type") == "Direct" else "mro"),
            "receiver": d.get("receiver"), "requester": d.get("requester"), "date": d.get("date"),
            "division_id": d.get("division_id"), "lines": out,
            "valuation_basis": None,
            "valuation_note": "MI inventory valuation basis not defined (no moving-average or PO-cost on stock). Monetary value intentionally not derived."}



@api.post("/mi")
async def create_mi(body: dict, user=Depends(current_user)):
    require(user, "create")
    source_type = body.get("source_type", "MRO")
    st = await _mi_settings()
    if source_type == "Direct" and not _can_direct_mi(user, st):
        raise HTTPException(403, "Direct MI tidak diizinkan untuk tenant/pengguna ini")
    source_mode = "direct" if source_type == "Direct" else "mro"
    did = gid(); no = await next_number("MI")
    await db.mi.insert_one({"id": did, "no": no, "date": body.get("date", now_iso()),
        "division_id": body.get("division_id"), "default_warehouse_id": body.get("default_warehouse_id"),
        "default_project_id": body.get("default_project_id"), "receiver": body.get("receiver"),
        "requester": body.get("requester"), "department": body.get("department"),
        "source_type": source_type, "source_mode": source_mode, "spk": body.get("spk"),
        "notes": body.get("notes"),
        "status": "Posted", "created_by": user.get("email"), "created_at": now_iso()})
    for l in body.get("lines", []):
        qty = float(l.get("qty", 0))
        if qty <= 0: continue
        mline = None
        if source_type == "MRO":
            # STRICT: MRO-mode line must originate from a valid MRO line with a matching item.
            if not l.get("mro_line_id"):
                raise HTTPException(400, "MI Dari MRO wajib bersumber dari baris MRO")
            mline = await db.mro_lines.find_one({"id": l["mro_line_id"]})
            if not mline:
                raise HTTPException(400, "Baris MRO sumber tidak ditemukan")
            if str(mline.get("item_id")) != str(l.get("item_id")):
                raise HTTPException(400, "Barang MI tidak sesuai dengan barang MRO sumber")
        # Warehouse LOCKED to the MRO line's warehouse in MRO mode (client override ignored).
        wh = (mline.get("warehouse_id") if (source_type == "MRO" and mline) else None) or l.get("warehouse_id") or body.get("default_warehouse_id")
        avail = await stock_balance(l["item_id"], wh)
        if qty > avail + 1e-6 and not has_perm(user, "override_qty"):
            raise HTTPException(400, f"Stok tidak cukup (tersedia {avail})")
        if mline and not has_perm(user, "override_qty"):
            rem = mline.get("qty", 0) - await alloc_out(l["mro_line_id"], "mi")
            if qty > rem + 1e-6:
                raise HTTPException(400, "Qty MI melebihi kebutuhan MRO")
        lid = gid()
        await db.mi_lines.insert_one({"id": lid, "mi_id": did, "mro_id": l.get("mro_id"),
            "mro_line_id": l.get("mro_line_id"),
            "item_id": l["item_id"], "qty": qty, "unit": l.get("unit"), "warehouse_id": wh,
            "project_id": l.get("project_id"), "unit_id": l.get("unit_id"),
            "spk": l.get("spk"), "notes": l.get("notes")})
        if l.get("mro_line_id"):
            await create_alloc("mro", l["mro_line_id"], l.get("mro_id"), "mi", lid, did, qty, l["item_id"])
        await post_ledger("MI", no, did, l["item_id"], wh, 0, qty,
                          project_id=l.get("project_id"), unit_id=l.get("unit_id"),
                          division_id=body.get("division_id"), user=user,
                          line_id=lid, uom=l.get("unit"), conversion_factor=l.get("conversion_factor", 1),
                          txn_at=body.get("date"), source_key=f"MI::{lid}")
    await audit(user, "create", "mi", did, no, after={"source_mode": source_mode})
    await notify("Barang dikeluarkan", f"MI {no} diposting", "mi", body.get("division_id"))
    return await get_mi(did, user)

# ================= INVENTORY VALUATION REPORTING + OPENING (moving average) =================
def _require_value(user):
    require(user, "view")
    if not has_perm(user, "view_purchase_price"):
        raise HTTPException(403, "Tidak memiliki akses nilai persediaan")


@api.get("/reports/valuation-summary")
async def valuation_summary(item_id: str = None, warehouse_id: str = None, user=Depends(current_user)):
    _require_value(user)
    m = await maps()
    q = {}
    if item_id: q["item_id"] = item_id
    if warehouse_id: q["warehouse_id"] = warehouse_id
    rows = await db.item_warehouse.find(q, {"_id": 0}).to_list(5000)
    out = []
    for r in rows:
        qty = float(r.get("current_stock") or 0)
        if qty == 0 and float(r.get("total_value") or 0) == 0:
            continue
        it = m["items"].get(r.get("item_id"), {})
        out.append({"item_id": r.get("item_id"), "item_name": it.get("name"), "item_code": it.get("code"),
                    "warehouse_id": r.get("warehouse_id"),
                    "warehouse_name": m["warehouses"].get(r.get("warehouse_id"), {}).get("name"),
                    "qty_on_hand": qty, "base_uom": it.get("base_uom_id"),
                    "avg_cost": float(r.get("avg_cost") or 0), "inventory_value": float(r.get("total_value") or 0)})
    out.sort(key=lambda x: (x["item_name"] or "", x["warehouse_name"] or ""))
    return {"method": "moving_weighted_average", "rows": out,
            "total_value": round(sum(x["inventory_value"] for x in out), 4)}


@api.get("/reports/valuation-ledger")
async def valuation_ledger(item_id: str = None, warehouse_id: str = None, doc_type: str = None,
                           date_from: str = None, date_to: str = None, user=Depends(current_user)):
    _require_value(user)
    m = await maps()
    q = {}
    if item_id: q["item_id"] = item_id
    if warehouse_id: q["warehouse_id"] = warehouse_id
    if doc_type: q["doc_type"] = doc_type
    rows = await db.valuation_ledger.find(q, {"_id": 0}).sort("at", 1).to_list(5000)
    def inrange(a):
        if date_from and (a or "") < date_from: return False
        if date_to and (a or "") > date_to + "T23:59:59": return False
        return True
    out = []
    for r in rows:
        if not inrange(r.get("at")): continue
        it = m["items"].get(r.get("item_id"), {})
        out.append({**{k: r.get(k) for k in ("doc_type", "doc_no", "at", "qty_in", "qty_out", "unit_cost",
                       "value_in", "value_out", "qty_before", "value_before", "avg_before",
                       "qty_after", "value_after", "avg_after", "valuation_method", "valuation_estimated")},
                    "item_name": it.get("name"),
                    "warehouse_name": m["warehouses"].get(r.get("warehouse_id"), {}).get("name")})
    return {"rows": out}


@api.get("/reports/valuation-reconcile")
async def valuation_reconcile(user=Depends(current_user)):
    """QA reconciliation + invalid-balance diagnostics for moving-average valuation.
    - stock qty (item_warehouse.current_stock) vs last valuation ledger qty_after per pool
    - invalid pools: qty<0, value<0, qty=0 but value!=0, qty>0 but missing average
    - duplicate valuation source_key, orphan valuation entries (no physical pool)
    """
    _require_value(user)
    m = await maps()
    pools = await db.item_warehouse.find({}, {"_id": 0}).to_list(10000)
    pool_keys = {(p.get("item_id"), p.get("warehouse_id")) for p in pools}
    mismatches = []; diagnostics = []

    def nm(r):
        return {"item_id": r.get("item_id"),
                "item_name": m["items"].get(r.get("item_id"), {}).get("name"),
                "warehouse_name": m["warehouses"].get(r.get("warehouse_id"), {}).get("name")}

    for r in pools:
        phys = float(r.get("current_stock") or 0)
        val = float(r.get("total_value") or 0)
        avg = float(r.get("avg_cost") or 0)
        last = await db.valuation_ledger.find({"item_id": r.get("item_id"), "warehouse_id": r.get("warehouse_id")},
                                              {"_id": 0}).sort("txn_at", -1).to_list(1)
        if last:
            val_qty = float(last[0].get("qty_after"))
            if abs(val_qty - phys) > 1e-6:
                mismatches.append({**nm(r), "physical_qty": phys, "valuation_qty": val_qty, "diff": phys - val_qty})
        if phys < -1e-6:
            diagnostics.append({**nm(r), "type": "negative_qty", "physical_qty": phys})
        if val < -1e-6:
            diagnostics.append({**nm(r), "type": "negative_value", "inventory_value": val})
        if abs(phys) < 1e-9 and abs(val) > 1e-6:
            diagnostics.append({**nm(r), "type": "zero_qty_nonzero_value", "inventory_value": val})
        if phys > 1e-6 and avg <= 0:
            diagnostics.append({**nm(r), "type": "missing_average", "physical_qty": phys, "inventory_value": val})

    # duplicate source_key
    seen = {}; dups = []
    vl = await db.valuation_ledger.find({}, {"_id": 0}).to_list(50000)
    for e in vl:
        sk = e.get("source_key")
        if not sk:
            continue
        seen[sk] = seen.get(sk, 0) + 1
    for sk, c in seen.items():
        if c > 1:
            dups.append({"type": "duplicate_source_key", "source_key": sk, "count": c})
    diagnostics.extend(dups)

    # orphan valuation entries: non-reversal movement referencing a pool that no longer exists
    orphans = []
    for e in vl:
        key = (e.get("item_id"), e.get("warehouse_id"))
        if key not in pool_keys:
            orphans.append({"type": "orphan_valuation_entry", "doc_type": e.get("doc_type"),
                            "doc_no": e.get("doc_no"), "item_id": e.get("item_id"),
                            "warehouse_id": e.get("warehouse_id")})
    diagnostics.extend(orphans[:200])

    return {"ok": len(mismatches) == 0 and len(diagnostics) == 0,
            "mismatches": mismatches, "diagnostics": diagnostics,
            "pool_count": len(pools)}


@api.get("/reports/mi-valuation/{mid}")
async def mi_valuation_report(mid: str, user=Depends(current_user)):
    """Authorized MI HPP report: per-line avg-cost snapshot + value out, with SPK HPP split."""
    _require_value(user)
    d = await db.mi.find_one({"id": mid}, {"_id": 0})
    if not d: raise HTTPException(404, "MI tidak ditemukan")
    m = await maps()
    entries = await db.valuation_ledger.find({"doc_id": mid}, {"_id": 0}).to_list(500)
    by_line = {e.get("line_id"): e for e in entries}
    lines = await db.mi_lines.find({"mi_id": mid}, {"_id": 0}).to_list(500)
    out = []; spk_tot = {}; total_out = 0.0
    for l in lines:
        e = by_line.get(l.get("id")) or {}
        vout = float(e.get("value_out") or 0); avg = float(e.get("unit_cost") or 0)
        total_out += vout
        allocs = await db.procurement_item_spk_allocations.find({"source_type": "mi", "item_line_id": l.get("id")}, {"_id": 0}).to_list(50)
        tot_alloc = sum(float(a.get("allocated_qty") or 0) for a in allocs) or 0
        spk_split = []
        for a in allocs:
            share = (float(a.get("allocated_qty") or 0) / tot_alloc) if tot_alloc > 0 else 0
            hpp = round(vout * share, 4)
            spk_split.append({"spk_id": a.get("spk_id"), "qty": a.get("allocated_qty"), "hpp": hpp})
            spk_tot[a.get("spk_id")] = round(spk_tot.get(a.get("spk_id"), 0) + hpp, 4)
        out.append({"mi_line_id": l.get("id"), "item_id": l.get("item_id"),
                    "item_name": m["items"].get(l.get("item_id"), {}).get("name"),
                    "qty_issue": float(l.get("qty") or 0), "unit": l.get("unit"),
                    "warehouse_name": m["warehouses"].get(l.get("warehouse_id"), {}).get("name"),
                    "project_id": l.get("project_id"), "unit_id": l.get("unit_id"),
                    "average_cost_at_posting": avg, "inventory_value_out": vout,
                    "valuation_method": e.get("valuation_method"), "spk_split": spk_split})
    return {"mi_id": mid, "mi_no": d.get("no"), "source_mode": d.get("source_mode"),
            "receiver": d.get("receiver"), "requester": d.get("requester"),
            "lines": out, "total_inventory_value_out": round(total_out, 4),
            "spk_hpp_totals": spk_tot}


def _opening_wh_scope(user):
    """Cakupan gudang Nilai Awal Persediaan: None = semua divisi; else set divisi user. Gudang tanpa
    divisi tetap terlihat (sama dengan allowed()/in_scope access control existing)."""
    if is_global(user):
        return None
    return {str(x) for x in ((user or {}).get("divisions") or []) if x}


def _wh_in_scope(wh, alw):
    return bool(wh) and (alw is None or not wh.get("division_id") or wh.get("division_id") in alw)


def _opening_import_candidate(iw):
    """Kandidat Opening Average Cost dari Import Saldo Awal (opening_inventory_layer):
    item_warehouse.opening_average_cost = Σ opening_value / Σ base_qty slice saldo awal
    (sudah per satuan dasar via faktor UOM barang). Bukan posting valuasi."""
    oq = float(iw.get("opening_qty") or 0)
    avg = float(iw.get("opening_average_cost") or 0)
    if oq <= 0 or avg <= 0:
        return None
    return round(avg, 6)


_OPENING_DOC_TYPES = ["Opening Balance", "Opening Balance Import"]
OPENING_MOVED_MSG = ("Sudah terdapat transaksi stok setelah saldo awal pada barang dan gudang ini. "
                     "Nilai awal tidak dapat ditetapkan otomatis; selesaikan/review transaksi tersebut terlebih dahulu.")


async def _pools_with_non_opening_moves(item_ids):
    """(item, gudang) yang punya movement stok NON-saldo-awal (termasuk yang sudah dibatalkan: HPP
    transaksi tsb mungkin sudah memakai avg_cost lama). Engine replay/revaluasi tidak tersedia, jadi
    pool seperti ini tidak boleh di-Tetapkan otomatis (rule konservatif)."""
    ids = sorted({i for i in item_ids if i})
    if not ids:
        return set()
    rows = await db.stock_ledger.find({"item_id": {"$in": ids}, "doc_type": {"$nin": _OPENING_DOC_TYPES}},
                                      {"_id": 0, "item_id": 1, "warehouse_id": 1}).to_list(200000)
    return {(r.get("item_id"), r.get("warehouse_id")) for r in rows}


def _has_opening_slice(iw):
    return float(iw.get("opening_qty") or 0) > 0


@api.get("/valuation/opening-candidates")
async def opening_candidates(q: str = None, warehouse_id: str = None, status: str = None,
                             user=Depends(current_user)):
    """List existing physical stock pools (qty>0) with their opening-valuation status.
    status filter: 'valued' (Sudah Dinilai) | 'unvalued' (Belum Dinilai)."""
    _require_value(user)
    m = await maps()
    alw = _opening_wh_scope(user)
    flt = {}
    if warehouse_id:
        flt["warehouse_id"] = warehouse_id
    rows = await db.item_warehouse.find(flt, {"_id": 0}).to_list(10000)
    rows = [r for r in rows if _wh_in_scope(m["warehouses"].get(r.get("warehouse_id")), alw)]
    opened = {(o.get("item_id"), o.get("warehouse_id"))
              for o in await db.valuation_ledger.find({"doc_type": "Opening Valuation"}, {"_id": 0}).to_list(10000)}
    moved = await _pools_with_non_opening_moves([r.get("item_id") for r in rows if _has_opening_slice(r)])
    out = []
    ql = (q or "").strip().lower()
    for r in rows:
        qty = float(r.get("current_stock") or 0)
        if qty <= 0:
            continue
        it = m["items"].get(r.get("item_id"), {})
        name = it.get("name") or ""; code = it.get("code") or ""
        if ql and ql not in name.lower() and ql not in code.lower():
            continue
        is_valued = (r.get("item_id"), r.get("warehouse_id")) in opened
        if status == "valued" and not is_valued:
            continue
        if status == "unvalued" and is_valued:
            continue
        buid = it.get("base_uom_id")
        cand = _opening_import_candidate(r)
        out.append({
            "item_id": r.get("item_id"), "item_code": code, "item_name": name,
            "warehouse_id": r.get("warehouse_id"),
            "warehouse_name": m["warehouses"].get(r.get("warehouse_id"), {}).get("name"),
            "qty_existing": qty, "base_uom": buid,
            "base_uom_name": (lambda u: u.get("symbol") or u.get("code") or u.get("name"))(m.get("uoms", {}).get(buid, {}) or {})
                              or (m.get("uoms", {}).get(buid, {}) or {}).get("name"),
            "avg_cost": float(r.get("avg_cost") or 0),
            "inventory_value": float(r.get("total_value") or 0),
            # Harga Beli Saldo Awal -> kandidat (status tetap Belum Dinilai sampai Tetapkan)
            "opening_cost_candidate": cand,
            "opening_cost_source": "Import Saldo Awal" if cand is not None else None,
            # Nilai opening = SLICE saldo awal (opening_qty x opening_average_cost), bukan qty saat ini.
            "opening_value_candidate": round(float(r.get("opening_value") or 0), 4) if cand is not None else None,
            "opening_import_qty": float(r.get("opening_qty") or 0) or None,
            "opening_blocked_reason": (OPENING_MOVED_MSG if (not is_valued and _has_opening_slice(r) and (
                (r.get("item_id"), r.get("warehouse_id")) in moved or abs(float(r.get("opening_qty") or 0) - qty) > 1e-9)) else None),
            "status": "valued" if is_valued else "unvalued"})
    out.sort(key=lambda x: (x["status"] != "unvalued", x["item_name"] or "", x["warehouse_name"] or ""))
    return {"rows": out}


@api.post("/valuation/opening")
async def post_opening_valuation(body: dict, user=Depends(current_user)):
    """Controlled Opening Inventory Valuation: establishes opening average/value for EXISTING
    physical qty WITHOUT adding stock. Does not duplicate physical quantity."""
    if not _is_admin_like(user) and not has_perm(user, "view_purchase_price"):
        raise HTTPException(403, "Tidak diizinkan")
    item_id = body.get("item_id"); wh = body.get("warehouse_id")
    cost = float(body.get("opening_avg_cost") or 0)
    cutoff = body.get("cutoff_date") or body.get("date") or now_iso()
    if not item_id or not wh:
        raise HTTPException(400, "item & gudang wajib")
    # tenant (proxy) -> izin (di atas) -> cakupan gudang -> business rule. Pesan generik.
    whd = await db.warehouses.find_one({"id": wh}, {"_id": 0})
    itd = await db.items.find_one({"id": item_id}, {"_id": 0, "id": 1})
    if not itd or not _wh_in_scope(whd, _opening_wh_scope(user)):
        raise HTTPException(404, "Barang atau gudang tidak ditemukan atau tidak dapat diakses")
    iw = await db.item_warehouse.find_one({"item_id": item_id, "warehouse_id": wh}) or {}
    qty = float(iw.get("current_stock") or 0)
    if qty <= 0:
        raise HTTPException(400, "Qty 0 tidak memerlukan opening valuation")
    if cost <= 0:
        raise HTTPException(400, "Opening Average Cost wajib > 0")
    exists = await db.valuation_ledger.find_one({"item_id": item_id, "warehouse_id": wh, "doc_type": "Opening Valuation"})
    if exists and not body.get("force"):
        raise HTTPException(400, "Opening valuation untuk pool ini sudah ada")
    # Pool dari Import Saldo Awal: hanya boleh ditetapkan selama qty pool == opening slice dan belum ada
    # movement non-saldo-awal (tidak ada engine replay HPP; histori tidak diubah otomatis).
    if _has_opening_slice(iw) and (abs(float(iw.get("opening_qty") or 0) - qty) > 1e-9
                                   or (item_id, wh) in await _pools_with_non_opening_moves([item_id])):
        raise HTTPException(400, OPENING_MOVED_MSG)
    from decimal import Decimal, ROUND_HALF_UP
    val = (Decimal(str(qty)) * Decimal(str(cost))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    # Guard atomik (CAS pada pool): Tetapkan ganda/bersamaan tidak membuat valuasi dua kali dan
    # tidak menimpa pool yang berubah (qty/_ver) sejak dibaca. Qty TIDAK diubah.
    vid = gid()
    ver = int(iw.get("_ver") or 0)
    cas = {"item_id": item_id, "warehouse_id": wh, "current_stock": iw.get("current_stock")}
    conds = [{"$or": [{"_ver": 0}, {"_ver": {"$exists": False}}, {"_ver": None}]}] if ver == 0 else [{"_ver": ver}]
    if not body.get("force"):
        conds.append({"$or": [{"opening_valuation_id": {"$exists": False}}, {"opening_valuation_id": None}]})
    cas["$and"] = conds
    won = await db.item_warehouse.find_one_and_update(
        cas, {"$set": {"avg_cost": cost, "total_value": float(val), "opening_valuation_id": vid, "_ver": ver + 1}},
        return_document=True)
    if won is None:
        again = await db.item_warehouse.find_one({"item_id": item_id, "warehouse_id": wh}) or {}
        if again.get("opening_valuation_id") or await db.valuation_ledger.find_one(
                {"item_id": item_id, "warehouse_id": wh, "doc_type": "Opening Valuation"}):
            raise HTTPException(400, "Opening valuation untuk pool ini sudah ada")
        raise HTTPException(409, "Stok gudang berubah saat penetapan nilai awal. Muat ulang lalu coba lagi.")
    await db.valuation_ledger.insert_one({
        "id": vid, "doc_type": "Opening Valuation", "doc_no": cutoff,
        "doc_id": gid(), "item_id": item_id, "warehouse_id": wh, "qty_in": 0, "qty_out": 0,
        "unit_cost": cost, "value_in": float(val), "value_out": 0,
        "qty_before": qty, "value_before": float(iw.get("total_value") or 0), "avg_before": float(iw.get("avg_cost") or 0),
        "qty_after": qty, "value_after": float(val), "avg_after": cost,
        "valuation_method": "moving_weighted_average", "valuation_estimated": False,
        "cutoff_date": cutoff, "notes": body.get("notes"), "user": user.get("email"),
        "txn_at": cutoff, "at": now_iso()})
    await audit(user, "create", "valuation", item_id, "Opening Valuation", after={"warehouse_id": wh, "qty": qty, "cost": cost, "cutoff": cutoff})
    return {"item_id": item_id, "warehouse_id": wh, "qty_on_hand": qty, "opening_avg_cost": cost, "inventory_value": float(val)}

