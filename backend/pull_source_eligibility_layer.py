"""Robust source eligibility for MRO -> RO / MI, RO -> PO and PO -> DO.

This layer fixes a legacy compatibility gap where list/detail treated request docs
without a `submitted` field as Open, while pull endpoints required
`submitted: true` explicitly. It also centralizes approval/cancel/outstanding
checks and keeps UOM display conversion plus source-header inheritance intact.
"""
from fastapi import Depends, Query

import uom_layer
import source_inheritance_layer
import doc_procurement


WAITING_OR_REJECTED = ["Waiting Approval", "Rejected"]


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _request_query():
    # Legacy request documents may not have `submitted`; list/detail historically
    # treated them as submitted/Open. Keep them eligible unless approval explicitly
    # says they are waiting/rejected.
    return {
        "cancelled": {"$ne": True},
        "approval_status": {"$nin": WAITING_OR_REJECTED},
        "$or": [
            {"submitted": True},
            {"submitted": {"$exists": False}},
        ],
    }


async def _attach_source_header(server, rows, collection, id_key):
    # P7: 1 query $in untuk seluruh header (dulu 1 find_one per dokumen); dokumen tak ditemukan -> {} (sama).
    ids = list(dict.fromkeys(r.get(id_key) for r in rows if r.get(id_key)))
    cache = {}
    if ids:
        for d in await getattr(server.db, collection).find({"id": {"$in": ids}}, {"_id": 0}).to_list(None):
            cache.setdefault(d.get("id"), d)
    for row in rows:
        did = row.get(id_key)
        if not did:
            continue
        row["source_header"] = source_inheritance_layer._header(cache.get(did) or {})
    return rows


async def _lines_by_doc(server, collection, fk, doc_ids, cap=2000):
    """P7: baris seluruh dokumen dalam 1 query $in. Urutan per dokumen identik dengan find per dokumen (urutan dasar
    adapter created_at, pk); batas per dokumen sama (2000)."""
    out = {i: [] for i in doc_ids}
    if doc_ids:
        for line in await getattr(server.db, collection).find({fk: {"$in": list(doc_ids)}}, {"_id": 0}).to_list(None):
            b = out.get(line.get(fk))
            if b is not None and len(b) < cap:
                b.append(line)
    return out


async def _alloc_out_many(server, line_ids, target_type):
    many = getattr(server, "alloc_out_many", None)
    if many is not None:
        return await many(line_ids, target_type)
    return {i: await server.alloc_out(i, target_type) for i in line_ids}


async def _mro_rows(server, target_type, user):
    m = await doc_procurement.maps()
    out = []
    docs = await server.db.mro.find(_request_query(), {"_id": 0}).to_list(3000)
    by_doc = await _lines_by_doc(server, "mro_lines", "mro_id", [d["id"] for d in docs])
    done = await _alloc_out_many(server, [ln["id"] for v in by_doc.values() for ln in v], target_type)
    for d in docs:
        lines = by_doc.get(d["id"], [])
        for line in lines:
            processed = done.get(line["id"], 0)
            outstanding = float(line.get("qty") or 0) - float(processed or 0)
            if outstanding <= 1e-9:
                continue
            doc_procurement.enrich_line(line, m)
            row = {
                "mro_id": d["id"], "mro_no": d.get("no"), "line_id": line["id"],
                "item_id": line.get("item_id"), "item_code": line.get("item_code"),
                "item_name": line.get("item_name"), "unit": line.get("unit"),
                "requested": line.get("qty", 0), "outstanding": outstanding,
                "notes": line.get("notes"),
                "warehouse_id": line.get("warehouse_id"), "project_id": line.get("project_id"),
                "unit_id": line.get("unit_id"), "warehouse_name": line.get("warehouse_name"),
                "project_name": line.get("project_name"), "unit_name": line.get("unit_name"),
            }
            if target_type == "ro":
                row["processed"] = processed
            else:
                row["issued"] = processed
                row["available"] = await server.stock_balance(line.get("item_id"), line.get("warehouse_id"))
            out.append(row)
    keys = ["requested", "outstanding", "processed"] if target_type == "ro" else ["requested", "issued", "outstanding", "available"]
    out = await uom_layer._convert_pull_rows(server, out, "mro_lines", keys)
    return await _attach_source_header(server, out, "mro", "mro_id")


async def _ro_rows(server, user):
    m = await doc_procurement.maps()
    out = []
    docs = await server.db.ro.find(_request_query(), {"_id": 0}).to_list(3000)
    by_doc = await _lines_by_doc(server, "ro_lines", "ro_id", [d["id"] for d in docs])
    all_lines = [ln for v in by_doc.values() for ln in v]
    done = await _alloc_out_many(server, [ln["id"] for ln in all_lines], "po")
    open_ids = [ln["id"] for ln in all_lines if float(ln.get("qty") or 0) - float(done.get(ln["id"], 0) or 0) > 1e-9]
    # sumber MRO pertama per baris RO (urutan dasar adapter, sama dengan find per baris) + nomor MRO (1 query $in)
    first_src = {}
    if open_ids:
        for a in await server.db.allocations.find({"target_line_id": {"$in": open_ids}, "source_type": "mro"}, {"_id": 0}).to_list(None):
            first_src.setdefault(a.get("target_line_id"), a)
    mro_ids = list({a.get("source_doc_id") for a in first_src.values()})
    mro_no_by_id = {}
    if mro_ids:
        for mh in await server.db.mro.find({"id": {"$in": mro_ids}}, {"_id": 0, "id": 1, "no": 1}).to_list(None):
            mro_no_by_id.setdefault(mh.get("id"), mh.get("no"))
    for d in docs:
        lines = by_doc.get(d["id"], [])
        # Nama project untuk RO ini: header + seluruh baris, unik dan urut (lebih dari satu project -> dipisah koma).
        pnames = []
        for pid in ([d.get("default_project_id")] if d.get("default_project_id") else []) + [ln.get("project_id") for ln in lines]:
            nm = (m["projects"].get(pid) or {}).get("name") if pid else None
            if nm and nm not in pnames:
                pnames.append(nm)
        ro_projects = ", ".join(pnames)
        for line in lines:
            ordered = done.get(line["id"], 0)
            outstanding = float(line.get("qty") or 0) - float(ordered or 0)
            if outstanding <= 1e-9:
                continue
            doc_procurement.enrich_line(line, m)
            src = first_src.get(line["id"])
            mro_no = mro_no_by_id.get(src.get("source_doc_id")) if src else None
            out.append({
                "ro_id": d["id"], "ro_no": d.get("no"), "mro_no": mro_no,
                "line_id": line["id"], "item_id": line.get("item_id"),
                "item_code": line.get("item_code"), "item_name": line.get("item_name"),
                "unit": line.get("unit"), "qty_ro": line.get("qty", 0),
                "ordered": ordered, "outstanding": outstanding,
                "notes": line.get("notes"),
                "warehouse_id": line.get("warehouse_id"), "project_id": line.get("project_id"),
                "unit_id": line.get("unit_id"), "warehouse_name": line.get("warehouse_name"),
                "project_name": line.get("project_name"), "project_names": ro_projects,
                "unit_name": line.get("unit_name"),
                "supplier_id": d.get("supplier_id"),
            })
    out = await uom_layer._convert_pull_rows(server, out, "ro_lines", ["qty_ro", "ordered", "outstanding"])
    return await _attach_source_header(server, out, "ro", "ro_id")


async def _po_rows(server, supplier_id, user):
    m = await doc_procurement.maps()
    out = []
    query = {
        "status": {"$in": ["Approved", "Partially Received"]},
        "cancelled": {"$ne": True},
        "approval_status": {"$nin": WAITING_OR_REJECTED},
    }
    if supplier_id:
        query["supplier_id"] = supplier_id
    docs = await server.db.po.find(query, {"_id": 0}).to_list(3000)
    # Edit DO: PO yang sudah diterima penuh OLEH DO INI tetap boleh tampil (sisa dihitung tanpa DO ini).
    import source_reservation_layer as _SR
    for d in await _SR.current_do_pos(server, supplier_id):
        if d["id"] not in {x["id"] for x in docs}:
            docs.append(d)
    by_doc = await _lines_by_doc(server, "po_lines", "po_id", list(dict.fromkeys(d["id"] for d in docs)))
    done = await _alloc_out_many(server, [ln["id"] for v in by_doc.values() for ln in v], "do")
    for d in docs:
        lines = by_doc.get(d["id"], [])
        for line in lines:
            received = done.get(line["id"], 0)
            outstanding = float(line.get("qty") or 0) - float(received or 0)
            if outstanding <= 1e-9:
                continue
            doc_procurement.enrich_line(line, m)
            out.append({
                "po_id": d["id"], "po_no": d.get("no"), "supplier_id": d.get("supplier_id"),
                "supplier_name": m["suppliers"].get(d.get("supplier_id"), {}).get("name"),
                "line_id": line["id"], "item_id": line.get("item_id"),
                "item_code": line.get("item_code"), "item_name": line.get("item_name"),
                "unit": line.get("unit"), "spk": d.get("spk") or line.get("spk"),
                "qty_po": line.get("qty", 0), "received": received, "outstanding": outstanding,
                "warehouse_id": line.get("warehouse_id"), "project_id": line.get("project_id"),
                "unit_id": line.get("unit_id"), "warehouse_name": line.get("warehouse_name"),
                "project_name": line.get("project_name"), "unit_name": line.get("unit_name"),
            })
    out = await uom_layer._convert_pull_rows(server, out, "po_lines", ["qty_po", "received", "outstanding"])
    return await _attach_source_header(server, out, "po", "po_id")


def install(server):
    app = server.app
    paths = [
        "/api/pull/mro-for-ro",
        "/api/pull/mro-for-mi",
        "/api/pull/ro-for-po",
        "/api/pull/po-for-do",
    ]
    for path in paths:
        route = _find_route(app, path, "GET")
        if route:
            app.router.routes.remove(route)

    async def pull_mro_for_ro(user=Depends(server.current_user)):
        return await _mro_rows(server, "ro", user)

    async def pull_mro_for_mi(user=Depends(server.current_user)):
        return await _mro_rows(server, "mi", user)

    async def pull_ro_for_po(user=Depends(server.current_user)):
        return await _ro_rows(server, user)

    async def pull_po_for_do(supplier_id: str = Query(None), user=Depends(server.current_user)):
        return await _po_rows(server, supplier_id, user)

    app.add_api_route("/api/pull/mro-for-ro", pull_mro_for_ro, methods=["GET"], tags=["pull-source"])
    app.add_api_route("/api/pull/mro-for-mi", pull_mro_for_mi, methods=["GET"], tags=["pull-source"])
    app.add_api_route("/api/pull/ro-for-po", pull_ro_for_po, methods=["GET"], tags=["pull-source"])
    app.add_api_route("/api/pull/po-for-do", pull_po_for_do, methods=["GET"], tags=["pull-source"])
