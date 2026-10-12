"""Dashboard, Reports, Traceability, Global Search, Notifications, Audit, Print/QR, Settings."""
from fastapi import Depends, HTTPException, Query
from server import (api, db, gid, now_iso, current_user, require, has_perm, is_global,
                    audit, alloc_out, next_number)


# ---------------- DASHBOARD ----------------
@api.get("/dashboard")
async def dashboard(user=Depends(current_user)):
    require(user, "view")
    # stock health
    iws = await db.item_warehouse.find({}, {"_id": 0}).to_list(10000)
    out_of, low, over, normal = 0, 0, 0, 0
    for iw in iws:
        cur = iw.get("current_stock", 0); mn = iw.get("min_stock", 0); mx = iw.get("max_stock", 0)
        if cur <= 0: out_of += 1
        elif cur <= mn: low += 1
        elif mx and cur > mx: over += 1
        else: normal += 1
    mro_open = await db.mro.count_documents({"submitted": True, "cancelled": {"$ne": True}})
    ro_open = await db.ro.count_documents({"submitted": True, "cancelled": {"$ne": True}})
    po_waiting = await db.po.count_documents({"status": "Waiting Approval"})
    po_open = await db.po.count_documents({"status": {"$in": ["Approved", "Partially Received"]}})
    do_today = await db.do.count_documents({"date": {"$gte": now_iso()[:10]}})
    mi_today = await db.mi.count_documents({"date": {"$gte": now_iso()[:10]}})
    loan_open = 0
    for l in await db.loans.find({}, {"_id": 0}).to_list(2000):
        lines = await db.loan_lines.find({"loan_id": l["id"]}, {"_id": 0}).to_list(500)
        if sum(max(0, x.get("qty", 0) - x.get("returned", 0)) for x in lines) > 0:
            loan_open += 1
    return {"stock": {"out_of_stock": out_of, "low_stock": low, "overstock": over, "normal": normal, "total": len(iws)},
            "mro_open": mro_open, "ro_open": ro_open, "po_waiting_approval": po_waiting, "po_outstanding": po_open,
            "do_today": do_today, "mi_today": mi_today, "loan_outstanding": loan_open,
            "counts": {"items": await db.items.count_documents({}), "warehouses": await db.warehouses.count_documents({}),
                       "suppliers": await db.suppliers.count_documents({}), "users": await db.users.count_documents({})}}


# ---------------- INVENTORY ----------------
@api.get("/inventory/ledger")
async def ledger(user=Depends(current_user), item_id: str = None, warehouse_id: str = None, limit: int = 500):
    require(user, "view")
    q = {}
    if item_id: q["item_id"] = item_id
    if warehouse_id: q["warehouse_id"] = warehouse_id
    rows = await db.stock_ledger.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
    im = {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)}
    wm = {w["id"]: w for w in await db.warehouses.find({}, {"_id": 0}).to_list(2000)}
    for r in rows:
        r["item_code"] = im.get(r["item_id"], {}).get("code"); r["item_name"] = im.get(r["item_id"], {}).get("name")
        r["warehouse_name"] = wm.get(r["warehouse_id"], {}).get("name")
    return rows


@api.get("/inventory/position")
async def stock_position(user=Depends(current_user)):
    require(user, "view")
    im = {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)}
    wm = {w["id"]: w for w in await db.warehouses.find({}, {"_id": 0}).to_list(2000)}
    rows = await db.item_warehouse.find({}, {"_id": 0}).to_list(10000)
    if not is_global(user) and user.get("divisions"):
        rows = [r for r in rows if im.get(r["item_id"], {}).get("division_id") in user["divisions"]]
    result = []
    for r in rows:
        it = im.get(r["item_id"], {})
        on_hand = r.get("current_stock", 0)
        # on order: approved PO lines outstanding for this item+warehouse
        result.append({"item_id": r["item_id"], "item_code": it.get("code"), "item_name": it.get("name"),
            "unit": it.get("unit"), "division_id": it.get("division_id"),
            "warehouse_id": r["warehouse_id"], "warehouse_name": wm.get(r["warehouse_id"], {}).get("name"),
            "on_hand": on_hand, "min_stock": r.get("min_stock", 0), "max_stock": r.get("max_stock", 0),
            "status": ("Out of Stock" if on_hand <= 0 else "Low Stock" if on_hand <= r.get("min_stock", 0)
                       else "Overstock" if r.get("max_stock", 0) and on_hand > r.get("max_stock", 0) else "Normal"),
            "suggested_order": max(0, r.get("max_stock", 0) - on_hand)})
    return result


# ---------------- TRACEABILITY ----------------
@api.get("/traceability/{mro_id:path}")
async def traceability(mro_id: str, user=Depends(current_user)):
    require(user, "view")
    mh = await db.mro.find_one({"id": mro_id}, {"_id": 0})
    if not mh:
        mh = await db.mro.find_one({"no": mro_id}, {"_id": 0})
    if not mh: raise HTTPException(404, "MRO tidak ditemukan")
    mro_id = mh["id"]
    im = {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)}
    lines = await db.mro_lines.find({"mro_id": mro_id}, {"_id": 0}).to_list(500)
    ro_set, po_set, do_set, mi_set = {}, {}, {}, {}
    rows = []
    for l in lines:
        it = im.get(l["item_id"], {})
        # RO
        ro_allocs = await db.allocations.find({"source_line_id": l["id"], "target_type": "ro"}, {"_id": 0}).to_list(100)
        qty_ro = sum(a["qty"] for a in ro_allocs)
        for a in ro_allocs:
            rh = await db.ro.find_one({"id": a["target_doc_id"]}, {"_id": 0})
            if rh: ro_set[rh["id"]] = rh["no"]
        # PO + received via ro
        qty_po = 0; qty_recv = 0; spks = set()
        for a in ro_allocs:
            po_allocs = await db.allocations.find({"source_line_id": a["target_line_id"], "target_type": "po"}, {"_id": 0}).to_list(100)
            for pa in po_allocs:
                qty_po += min(a["qty"], pa["qty"])
                ph = await db.po.find_one({"id": pa["target_doc_id"]}, {"_id": 0})
                if ph: po_set[ph["id"]] = ph["no"]
                pline = await db.po_lines.find_one({"id": pa["target_line_id"]}, {"_id": 0})
                if pline and pline.get("spk"): spks.add(pline["spk"])
                do_allocs = await db.allocations.find({"source_line_id": pa["target_line_id"], "target_type": "do"}, {"_id": 0}).to_list(100)
                for da in do_allocs:
                    qty_recv += da["qty"]
                    dh = await db.do.find_one({"id": da["target_doc_id"]}, {"_id": 0})
                    if dh: do_set[dh["id"]] = dh["no"]
        # MI
        mi_allocs = await db.allocations.find({"source_line_id": l["id"], "target_type": "mi"}, {"_id": 0}).to_list(100)
        qty_mi = sum(a["qty"] for a in mi_allocs)
        for a in mi_allocs:
            mih = await db.mi.find_one({"id": a["target_doc_id"]}, {"_id": 0})
            if mih: mi_set[mih["id"]] = mih["no"]
        rows.append({"item_code": it.get("code"), "item_name": it.get("name"), "unit": it.get("unit"),
            "request": l.get("qty", 0), "qty_ro": qty_ro, "qty_po": qty_po, "qty_received": qty_recv,
            "qty_mi": qty_mi, "spk": sorted(spks), "outstanding": max(0, l.get("qty", 0) - qty_mi)})
    def dl(s, t): return [{"id": k, "no": v, "type": t} for k, v in s.items()]
    return {"mro": {"id": mh["id"], "no": mh["no"], "date": mh.get("date")}, "rows": rows,
            "documents": {"RO": dl(ro_set, "ro"), "PO": dl(po_set, "po"), "DO": dl(do_set, "do"), "MI": dl(mi_set, "mi")}}


@api.get("/reports/mro-traceability")
async def mro_traceability_report(user=Depends(current_user)):
    require(user, "view")
    out = []
    for mh in await db.mro.find({}, {"_id": 0}).sort("created_at", -1).to_list(500):
        t = await traceability(mh["id"], user)
        total_req = sum(r["request"] for r in t["rows"])
        total_mi = sum(r["qty_mi"] for r in t["rows"])
        status = "Completed" if total_req > 0 and total_mi >= total_req else ("Partial" if total_mi > 0 else "Open")
        out.append({"mro_no": mh["no"], "mro_id": mh["id"], "date": mh.get("date"),
            "request": total_req, "qty_ro": sum(r["qty_ro"] for r in t["rows"]),
            "qty_po": sum(r["qty_po"] for r in t["rows"]), "qty_received": sum(r["qty_received"] for r in t["rows"]),
            "qty_mi": total_mi, "outstanding": sum(r["outstanding"] for r in t["rows"]), "status": status})
    return out


@api.get("/reports/unit-usage")
async def unit_usage(user=Depends(current_user), unit_id: str = None):
    require(user, "view")
    q = {"qty_out": {"$gt": 0}, "doc_type": "MI"}
    if unit_id: q["unit_id"] = unit_id
    rows = await db.stock_ledger.find(q, {"_id": 0}).to_list(10000)
    im = {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)}
    um = {u["id"]: u for u in await db.units.find({}, {"_id": 0}).to_list(2000)}
    agg = {}
    for r in rows:
        if not r.get("unit_id"): continue
        key = (r["unit_id"], r["item_id"])
        agg.setdefault(key, 0)
        agg[key] += r.get("qty_out", 0)
    return [{"unit_id": k[0], "unit_name": um.get(k[0], {}).get("name"), "plate_no": um.get(k[0], {}).get("plate_no"),
             "item_code": im.get(k[1], {}).get("code"), "item_name": im.get(k[1], {}).get("name"),
             "unit": im.get(k[1], {}).get("unit"), "qty": v} for k, v in agg.items()]


@api.get("/reports/lead-time")
async def lead_time(user=Depends(current_user)):
    require(user, "view")
    from datetime import datetime
    out = []
    for mh in await db.mro.find({}, {"_id": 0}).sort("created_at", -1).to_list(300):
        t = await traceability(mh["id"], user)
        po_no = t["documents"]["PO"][0]["no"] if t["documents"]["PO"] else None
        do_no = t["documents"]["DO"][0]["no"] if t["documents"]["DO"] else None
        mi_no = t["documents"]["MI"][0]["no"] if t["documents"]["MI"] else None
        def d(x): return datetime.fromisoformat(x) if x else None
        mro_d = d(mh.get("date"))
        po_d = do_d = mi_d = None
        if t["documents"]["PO"]:
            ph = await db.po.find_one({"id": t["documents"]["PO"][0]["id"]}, {"_id": 0}); po_d = d(ph.get("date")) if ph else None
        if t["documents"]["DO"]:
            dh = await db.do.find_one({"id": t["documents"]["DO"][0]["id"]}, {"_id": 0}); do_d = d(dh.get("date")) if dh else None
        if t["documents"]["MI"]:
            mih = await db.mi.find_one({"id": t["documents"]["MI"][0]["id"]}, {"_id": 0}); mi_d = d(mih.get("date")) if mih else None
        def diff(a, b): return (b - a).days if a and b else None
        out.append({"mro_no": mh["no"], "po_no": po_no, "do_no": do_no, "mi_no": mi_no,
            "mro_to_po": diff(mro_d, po_d), "po_to_do": diff(po_d, do_d), "do_to_mi": diff(do_d, mi_d),
            "total": diff(mro_d, mi_d)})
    return out


# ---------------- GLOBAL SEARCH ----------------
@api.get("/search")
async def global_search(q: str, user=Depends(current_user)):
    require(user, "view")
    ql = q.strip().lower()
    res = []
    async def scan(col, dtype, fields):
        for d in await col.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000):
            hay = " ".join(str(d.get(f, "")) for f in fields).lower()
            if ql in hay:
                res.append({"type": dtype, "id": d["id"], "no": d.get("no") or d.get("code"),
                            "label": d.get("name") or d.get("supplier_invoice") or d.get("no")})
    await scan(db.mro, "mro", ["no", "requester", "notes"])
    await scan(db.ro, "ro", ["no", "requester"])
    await scan(db.po, "po", ["no", "supplier_notes"])
    await scan(db.do, "do", ["no", "supplier_dn", "supplier_invoice"])
    await scan(db.mi, "mi", ["no", "receiver"])
    await scan(db.suppliers, "suppliers", ["code", "name"])
    await scan(db.items, "items", ["code", "name", "part_number"])
    await scan(db.projects, "projects", ["code", "name"])
    await scan(db.units, "units", ["code", "name", "plate_no"])
    return res[:60]


# ---------------- NOTIFICATIONS ----------------
@api.get("/notifications")
async def list_notifications(user=Depends(current_user)):
    q = {}
    if not is_global(user) and user.get("divisions"):
        q = {"$or": [{"division": {"$in": user["divisions"]}}, {"division": None}]}
    return await db.notifications.find(q, {"_id": 0}).sort("at", -1).to_list(100)


@api.post("/notifications/{nid}/read")
async def read_notification(nid: str, user=Depends(current_user)):
    await db.notifications.update_one({"id": nid}, {"$set": {"read": True}})
    return {"ok": True}


@api.post("/notifications/read-all")
async def read_all_notifications(user=Depends(current_user)):
    await db.notifications.update_many({}, {"$set": {"read": True}})
    return {"ok": True}


# ---------------- AUDIT ----------------
@api.get("/audit")
async def list_audit(user=Depends(current_user), entity: str = None, entity_id: str = None, limit: int = 300):
    require(user, "view")
    q = {}
    if entity: q["entity"] = entity
    if entity_id: q["entity_id"] = entity_id
    return await db.audit_logs.find(q, {"_id": 0}).sort("at", -1).to_list(limit)


# ---------------- SETTINGS ----------------
@api.get("/settings/{key}")
async def get_setting(key: str, user=Depends(current_user)):
    s = await db.settings.find_one({"id": key}, {"_id": 0})
    return s or {}


@api.put("/settings/{key}")
async def update_setting(key: str, body: dict, user=Depends(current_user)):
    require(user, "edit")
    body.pop("_id", None); body["id"] = key
    await db.settings.update_one({"id": key}, {"$set": body}, upsert=True)
    await audit(user, "edit", "settings", key)
    return await db.settings.find_one({"id": key}, {"_id": 0})


# ---------------- PRINT TEMPLATES ----------------
@api.get("/print-templates")
async def list_templates(user=Depends(current_user), doc_type: str = None):
    q = {}
    if doc_type: q["doc_type"] = doc_type
    return await db.print_templates.find(q, {"_id": 0}).to_list(200)


@api.post("/print-templates")
async def create_template(body: dict, user=Depends(current_user)):
    require(user, "create")
    doc = {**body, "id": gid(), "created_at": now_iso()}
    doc.pop("_id", None)
    await db.print_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.put("/print-templates/{tid}")
async def update_template(tid: str, body: dict, user=Depends(current_user)):
    require(user, "edit")
    body.pop("id", None); body.pop("_id", None)
    await db.print_templates.update_one({"id": tid}, {"$set": body})
    return await db.print_templates.find_one({"id": tid}, {"_id": 0})


@api.delete("/print-templates/{tid}")
async def delete_template(tid: str, user=Depends(current_user)):
    require(user, "delete")
    await db.print_templates.delete_one({"id": tid})
    return {"ok": True}


# ---------------- QR VERIFICATION ----------------
@api.post("/verify/generate")
async def generate_verification(body: dict, user=Depends(current_user)):
    require(user, "print")
    code = gid()[:12].upper()
    await db.verifications.insert_one({"id": gid(), "code": code, "doc_type": body["doc_type"],
        "doc_id": body["doc_id"], "doc_no": body.get("doc_no"), "status": body.get("status"),
        "created_by": user.get("name"), "created_at": now_iso()})
    await audit(user, "print", body["doc_type"], body["doc_id"], body.get("doc_no"))
    return {"code": code}


@api.get("/verify/{code}")
async def verify_document(code: str):
    v = await db.verifications.find_one({"code": code.upper()}, {"_id": 0})
    if not v:
        return {"valid": False, "message": "Kode verifikasi tidak ditemukan"}
    return {"valid": True, "doc_type": v["doc_type"], "doc_no": v.get("doc_no"),
            "status": v.get("status"), "created_by": v.get("created_by"), "created_at": v.get("created_at")}
